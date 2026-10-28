# Changelog

All notable changes to KasaOS. Versions follow semantic versioning.

## [1.1.1] — 2026-10-28

- Personel listesinde "Durum" sütunu artık kesilmeden görünüyor
- Yayın öncesi paket doğrulaması eklendi (imza anahtarı, sürüm ve güncelleme kaynağı)

## [1.1.0] — 2026-10-28

### Yeni: Personel takibi
- Personel ekleme, düzenleme, ayrılanları arşivleme (geçmiş korunur)
- Her personel için bakiye: kime ne kadar borçlusunuz, kim size ne kadar borçlu
- Hareketler: hak ediş (maaş, prim, mesai), ödeme / avans, tahsilat, kesinti
- Ödeme ve tahsilatlar kasaya ve "Personel" giderine otomatik işlenir
- Günlük ücretli (yevmiyeli) personel: çalışma şekli ve günlük ücret
- **Günlük Yoklama:** o gün çalışanları işaretleyip yevmiyeleri tek seferde yazma; aynı gün
  ödenenler için "Ödendi" ile ödeme de kasadan düşülür; aynı güne iki kez yevmiye yazılamaz
- Personel detayında "bu ay kaç gün çalıştı"
- Veritabanı otomatik güncellenir (öncesinde yedek alınır); gerekirse 1.0.0'a geri dönülebilir

## [1.0.0] — 2026-10-28

İlk sürüm.

- Hızlı gelir / gider girişi (klavye odaklı, "Kaydet ve Yeni", çift kayıt koruması)
- Genel bakış: günlük ve aylık özet, nakit kasa bakiyesi, kart tahsilatı, grafikler
- Kasa yönetimi: hesap bakiyeleri, gün açılış/kapanış sayımı ve fark
- Transfer, sahip çekişi ve sermaye girişi (gelir/gider sayılmaz)
- İşlem geçmişi: filtreleme, arama, düzenleme, silme ve değişiklik geçmişi
- Raporlar: kategori ve ödeme yöntemi dağılımı, CSV dışa aktarım
- Kategoriler, ödeme yöntemleri ve hesap yönetimi
- Doğrulanmış yedekleme ve güvenli geri yükleme
- İmzalı, aşamalı ve geri alınabilir otomatik güncelleme altyapısı
