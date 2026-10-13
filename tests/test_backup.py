"""Backup-ul: copie consistentă cu aplicația pornită, fișierele din instance/, rotație."""
import importlib.util
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("backup", Path(__file__).parent.parent / "scripts" / "backup.py")
backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backup)


@pytest.fixture
def instanta(tmp_path):
    director = tmp_path / "instance"
    director.mkdir()
    baza = sqlite3.connect(director / "inventar.db")
    baza.execute("PRAGMA journal_mode=WAL")
    baza.execute("CREATE TABLE t (x INTEGER)")
    baza.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1000)])
    baza.commit()
    (director / "secret.key").write_text("cheie")
    return director, baza


def test_backup_complet_si_restaurabil(instanta, tmp_path):
    director, baza = instanta
    # Scrieri neconfirmate în WAL trebuie să nu strice copia.
    baza.execute("INSERT INTO t VALUES (-1)")
    copie = backup.fa_backup(director / "inventar.db", director, tmp_path / "bk", datetime(2026, 1, 2, 3, 4, 5))
    assert copie.name == "inventar_2026-01-02_030405"
    assert (copie / "secret.key").read_text() == "cheie"
    restaurata = sqlite3.connect(copie / "inventar.db")
    assert restaurata.execute("SELECT count(*) FROM t").fetchone()[0] == 1000
    assert restaurata.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    restaurata.close()
    baza.close()


def test_backup_in_timp_ce_aplicatia_scrie(instanta, tmp_path):
    director, baza = instanta
    baza.close()
    gata = threading.Event()

    def scrie():
        conexiune = sqlite3.connect(director / "inventar.db", timeout=5)
        while not gata.is_set():
            conexiune.execute("INSERT INTO t VALUES (1)")
            conexiune.commit()
        conexiune.close()

    fir = threading.Thread(target=scrie)
    fir.start()
    try:
        copie = backup.fa_backup(director / "inventar.db", director, tmp_path / "bk")
    finally:
        gata.set()
        fir.join()
    verificare = sqlite3.connect(copie / "inventar.db")
    assert verificare.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert verificare.execute("SELECT count(*) FROM t").fetchone()[0] >= 1000
    verificare.close()


def test_rotatie(tmp_path):
    for zi in range(1, 6):
        (tmp_path / f"inventar_2026-01-0{zi}_000000").mkdir()
    (tmp_path / "alt_director").mkdir()
    sterse = backup.curata(tmp_path, 3)
    assert [p.name for p in sterse] == ["inventar_2026-01-01_000000", "inventar_2026-01-02_000000"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "alt_director", "inventar_2026-01-03_000000", "inventar_2026-01-04_000000", "inventar_2026-01-05_000000"]


def test_cod_de_iesire(instanta, tmp_path):
    director, baza = instanta
    baza.close()
    assert backup.main(["--destinatie", str(tmp_path / "bk"), "--instanta", str(director)]) == 0
    assert backup.main(["--destinatie", str(tmp_path / "bk"), "--instanta", str(tmp_path / "lipsa")]) == 1
