"""Teste de fum pentru PDF-uri (§13): se extrage textul cu pypdf și se verifică esențialul."""
import time
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from pypdf import PdfReader

from inventar.domain.comisii import MembruNou, creeaza_comisie
from inventar.domain.comun import EroareValidare
from inventar.domain.generare import Perimetru, genereaza
from inventar.domain.setari import salveaza_setari
from inventar.pdf.lista import Antet, Lista, RandLista, cont_in_margine, deseneaza_liste
from inventar.tiparire import tipareste_declaratii, tipareste_liste
from tests.conftest import ADMIN_CLI, CONSULTARE, OPERATOR

D = date(2025, 11, 28)


def text(continut: bytes) -> list[str]:
    return [pagina.extract_text() for pagina in PdfReader(BytesIO(continut)).pages]


@pytest.fixture
def inventar(session, persoana, bunuri, initial, nom, tmp_path):
    salveaza_setari(session, ADMIN_CLI, {
        "unitate": "A.J.F.P. BOTOSANI", "unitate_superioara": "D.G.R.F.P. IASI",
        "antet_declaratii_1": "Agenţia Naţională de Administrare Fiscală",
        "antet_declaratii_2": "DGRFP IAŞI - A.J.F.P. Botoşani",
    })
    marcela = persoana("HRITCU MARCELA")
    b1 = bunuri("114729", cont="213.03.01", pret="4034.10", serie="20WWM42",
                data_amortizare_integrala=date(2022, 12, 20))[0]
    b2 = bunuri("116901", cont="213.03.01", pret="2983.64")[0]
    b3 = bunuri("117367", cont="213.03.01", pret="4641.00", nr_inventar_vechi="5184")[0]
    initial(date(2025, 1, 1), [(b1, marcela), (b2, marcela), (b3, marcela)])
    creeaza_comisie(session, OPERATOR, nom["botosani"].id, date(2025, 1, 1), None,
                    [MembruNou("Brânduşa-Liliana Lucaci", "PRESEDINTE"), MembruNou("Liliana Gherasă", "MEMBRU")])
    return genereaza(session, OPERATOR, D, Perimetru())


def test_lista_14_3_12(session, inventar, tmp_path):
    nume, continut = tipareste_liste(session, CONSULTARE, inventar.id, "MF", tmp_path)
    assert nume == "Inventar_2025-11-28_tiraj_MF.pdf"
    [pagina] = text(continut)
    for asteptat in ("LISTA DE INVENTARIERE", "28 noiembrie 2025", "11658,74", "Pagina 1 din 1",
                     "COD: 14-3-12", "Brânduşa-Liliana Lucaci", "Liliana Gherasă", "HRITCU MARCELA",
                     "inventarierii", "4034,10", "seria 20WWM42", "5184", "20.12.2022", "213.03",
                     "Total pentru gestiunea HRITCU MARCELA / Botosani"):
        assert asteptat in pagina, asteptat
    assert "invetarierii" not in pagina


def test_lista_pe_gestiune(session, inventar, tmp_path):
    from sqlalchemy import select

    from inventar.models import InventarLinie

    persoana_id = session.scalar(select(InventarLinie.persoana_id).where(InventarLinie.inventar_id == inventar.id))
    nume, continut = tipareste_liste(session, OPERATOR, inventar.id, "MF", tmp_path, persoana_id=persoana_id)
    assert nume == "Inventar_2025-11-28_HRITCU_MARCELA_MF.pdf"
    assert "Pagina 1 din 1" in text(continut)[0]


def test_declaratii(session, inventar):
    _, inceput = tipareste_declaratii(session, OPERATOR, inventar.id, "MF", "inceput")
    [pagina] = text(inceput)
    for asteptat in ("DECLARAŢIE DE INVENTAR", "Subsemnatul HRITCU MARCELA", "mijloacelor fixe",
                     "Agenţia Naţională de Administrare Fiscală", "DGRFP IAŞI", "Botosani - Mijloace Fixe",
                     "(11)", "Data: 28 noiembrie 2025", "Brânduşa-Liliana Lucaci"):
        assert asteptat in pagina, asteptat
    _, sfarsit = tipareste_declaratii(session, OPERATOR, inventar.id, "MF", "sfarsit")
    [pagina] = text(sfarsit)
    assert "DECLARAŢIE DE SFÂRŞIT DE INVENTAR" in pagina and "locaţia Botosani" in pagina
    assert "din cadrul A.J.F.P. BOTOSANI" in pagina


def test_tiparirea_scrie_in_jurnal(session, inventar, tmp_path):
    from sqlalchemy import select

    from inventar.models import Jurnal

    tipareste_liste(session, OPERATOR, inventar.id, "MF", tmp_path)
    tipareste_declaratii(session, OPERATOR, inventar.id, "MF", "sfarsit")
    actiuni = list(session.scalars(select(Jurnal.actiune).where(Jurnal.actiune.like("PDF_%")).order_by(Jurnal.id)))
    assert actiuni == ["PDF_LISTE", "PDF_DECLARATII"]


def test_inventar_neactualizat_nu_se_tipareste(session, inventar, tmp_path):
    inventar.stare = "NEACTUALIZAT"
    session.commit()
    with pytest.raises(EroareValidare, match="regenerați"):
        tipareste_liste(session, OPERATOR, inventar.id, "MF", tmp_path)


def test_categorie_fara_bunuri(session, inventar, tmp_path):
    with pytest.raises(EroareValidare, match="Nu există bunuri"):
        tipareste_liste(session, OPERATOR, inventar.id, "OI", tmp_path)


def test_cont_in_margine():
    assert cont_in_margine("303.02.00.04", 2) == "303.02"
    assert cont_in_margine("303.02.00.04", 1) == "303"
    assert cont_in_margine("213", 2) == "213"


def _lista(n: int, nume: str = "POP ION") -> Lista:
    randuri = [RandLista(str(100000 + i), None, f"BUN CU O DENUMIRE DESTUL DE LUNGA CA SA SE RUPA PE DOUA RANDURI {i}",
                         "S123" if i % 3 == 0 else None, "BUC", Decimal("10.50"), "303.02.00.04", None)
               for i in range(n)]
    return Lista("OI", "303", nume, nume, "Botosani", ["A", "B", "C"], randuri)


def test_paginare_lista_lunga():
    antet = Antet(D, "U", "US", None)
    pagini = text(deseneaza_liste([_lista(80), _lista(1, "ALT")], antet))
    total = len(pagini)
    assert total >= 4
    assert all(f"din {total}" in p for p in pagini)
    # Fiecare pagină are antetul și blocul de semnături; totalul apare o singură dată pe listă.
    assert all("LISTA DE INVENTARIERE" in p and "Semnatura" in p for p in pagini)
    assert sum("Total pentru gestiunea POP ION" in p for p in pagini) == 1
    assert "Total pentru gestiunea POP ION" in pagini[-2]
    assert "840,00" in pagini[-2]  # 80 × 10,50
    # Numărul paginii din antet numără în cadrul listei: ultima listă reîncepe de la 1.
    assert "Pagina" in pagini[-1] and "ALT" in pagini[-1]


def test_tiraj_mare_sub_un_minut():
    """~300 de pagini (§10.4): câteva sute de liste mici și câteva mari."""
    liste = [_lista(8, f"GESTIUNE {i}") for i in range(250)] + [_lista(120, f"MARE {i}") for i in range(5)]
    start = time.perf_counter()
    continut = deseneaza_liste(liste, Antet(D, "U", "US", None))
    durata = time.perf_counter() - start
    assert len(PdfReader(BytesIO(continut)).pages) >= 280
    assert durata < 60, durata
