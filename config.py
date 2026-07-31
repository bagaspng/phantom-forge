# config.py
from dataclasses import dataclass, field

@dataclass
class Config:
    url: str = "https://idnog.or.id/contact"
    
    # Selector-selector khusus non-dinamis (seperti checkbox & tombol submit)
    robot_checkbox_selector: str = "[type='checkbox']"
    submit_selector: str         = "button[type='submit']"
    
    # Data dinamis (Data Bank)
    # Kunci dictionary ini akan dicocokkan (secara parsial) dengan name atribut pada form
    form_data_bank: dict = field(default_factory=lambda: {
        "nama": "budi",
        "name": "Vora Arsitek",
        "first_name": "Vora",
        "last_name": "Arsitek",
        "judul": "Pengujian Sistem SPA",
        "title": "Pengujian Sistem SPA",
        "subject": "Pengujian Sistem SPA",
        "email": "vora@test-domain.io",
        "mail": "vora@test-domain.io",
        "phone": "08123456789",
        "telepon": "08123456789",
        "telp": "08123456789",
        "alamat": "Jl. Pegangsaan Timur No. 56",
        "address": "Jl. Pegangsaan Timur No. 56",
        "pesan": "Pesan uji coba automasi hybrid pada SPA.",
        "isipesan": "Pesan uji coba automasi hybrid pada SPA.",
        "message": "Pesan uji coba automasi hybrid pada SPA.",
        "body": "Isi pesan kontak dari automasi bot.",
        "desc": "Deskripsi uji coba.",
        "paket": "Paket Premium",
        "company": "Vora Tech"
    })

QNN_CONFIG = Config()
