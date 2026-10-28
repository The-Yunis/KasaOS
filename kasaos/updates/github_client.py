"""Minimal GitHub Releases client (stdlib urllib, HTTPS only, timeouts everywhere)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Protocol

from kasaos.core.exceptions import UpdateError
from kasaos.version import __version__

log = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT = 15
ALLOWED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com")


@dataclass
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass
class Release:
    tag: str
    name: str
    body: str
    prerelease: bool
    assets: dict[str, ReleaseAsset] = field(default_factory=dict)


class Transport(Protocol):
    def get(self, url: str, timeout: float, headers: dict[str, str]) -> "Response": ...


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    stream: object  # file-like with .read(n)

    def read_all(self, limit: int) -> bytes:
        data = self.stream.read(limit + 1)
        if len(data) > limit:
            raise UpdateError("Sunucudan beklenenden büyük yanıt geldi.")
        return data


class UrllibTransport:
    def get(self, url: str, timeout: float, headers: dict[str, str]) -> Response:
        _require_https(url)
        req = urllib.request.Request(url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)  # TLS verification on by default
        except urllib.error.HTTPError as e:
            return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise UpdateError(f"Güncelleme sunucusuna ulaşılamadı: {getattr(e, 'reason', e)}") from e
        _require_https(resp.geturl())
        return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp)


def _require_https(url: str) -> None:
    if urllib.parse.urlparse(url).scheme != "https":
        raise UpdateError("Güvensiz (HTTPS olmayan) güncelleme bağlantısı reddedildi.")


def _check_download_host(url: str) -> None:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_DOWNLOAD_HOSTS):
        raise UpdateError(f"Güncelleme dosyası beklenmeyen bir sunucuda: {host}")


class GitHubReleaseClient:
    def __init__(self, owner: str, repo: str, transport: Transport | None = None):
        if not owner or not repo:
            raise UpdateError("Güncelleme kaynağı (GitHub deposu) yapılandırılmamış.")
        safe = all(ch.isalnum() or ch in "-_." for ch in owner + repo)
        if not safe:
            raise UpdateError("GitHub depo adı geçersiz.")
        self.owner, self.repo = owner, repo
        self.transport = transport or UrllibTransport()
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": f"KasaOS/{__version__}",
                        "X-GitHub-Api-Version": "2022-11-28"}

    def releases(self, include_prerelease: bool = False) -> list[Release]:
        url = f"{API}/repos/{self.owner}/{self.repo}/releases?per_page=20"
        resp = self.transport.get(url, TIMEOUT, self.headers)
        if resp.status in (403, 429) and (resp.headers.get("x-ratelimit-remaining") == "0" or resp.status == 429):
            raise UpdateError("GitHub istek sınırına ulaşıldı. Daha sonra tekrar deneyin.")
        if resp.status == 404:
            raise UpdateError("Güncelleme deposu bulunamadı.")
        if resp.status != 200:
            raise UpdateError(f"GitHub beklenmeyen yanıt döndürdü (HTTP {resp.status}).")
        try:
            data = json.loads(resp.read_all(5 * 1024 * 1024).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise UpdateError("GitHub yanıtı okunamadı.") from None
        if not isinstance(data, list):
            raise UpdateError("GitHub yanıtı beklenen biçimde değil.")
        out = []
        for r in data:
            try:
                if r.get("draft"):
                    continue
                if r.get("prerelease") and not include_prerelease:
                    continue
                rel = Release(str(r["tag_name"]), str(r.get("name") or r["tag_name"]), str(r.get("body") or ""),
                              bool(r.get("prerelease")))
                for a in r.get("assets") or []:
                    rel.assets[str(a["name"])] = ReleaseAsset(str(a["name"]), str(a["browser_download_url"]),
                                                              int(a.get("size") or 0))
                out.append(rel)
            except (KeyError, TypeError, ValueError, AttributeError):
                log.warning("Skipping malformed release entry")
        return out

    def fetch_small(self, asset: ReleaseAsset, limit: int) -> bytes:
        _check_download_host(asset.url)
        resp = self.transport.get(asset.url, TIMEOUT, {"User-Agent": self.headers["User-Agent"],
                                                        "Accept": "application/octet-stream"})
        if resp.status != 200:
            raise UpdateError(f"{asset.name} indirilemedi (HTTP {resp.status}).")
        return resp.read_all(limit)

    def download(self, asset: ReleaseAsset, dest, expected_size: int,
                 progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> None:
        _check_download_host(asset.url)
        resp = self.transport.get(asset.url, 60, {"User-Agent": self.headers["User-Agent"],
                                                   "Accept": "application/octet-stream"})
        if resp.status != 200:
            raise UpdateError(f"Güncelleme dosyası indirilemedi (HTTP {resp.status}).")
        received = 0
        with open(dest, "wb") as fh:
            while True:
                if cancelled and cancelled():
                    raise UpdateError("İndirme iptal edildi.")
                try:
                    chunk = resp.stream.read(64 * 1024)
                except (OSError, TimeoutError) as e:
                    raise UpdateError(f"İndirme yarıda kesildi: {e}") from e
                if not chunk:
                    break
                received += len(chunk)
                if received > expected_size:
                    raise UpdateError("İndirilen dosya beklenenden büyük.")
                fh.write(chunk)
                if progress:
                    progress(received, expected_size)
        if received != expected_size:
            raise UpdateError(f"İndirme eksik kaldı ({received}/{expected_size} bayt).")
