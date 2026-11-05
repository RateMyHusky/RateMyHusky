import pytest
from pipeline.names import search_fold, search_squash, tidy_name

@pytest.mark.parametrize("raw, want", [
    ("David O&#39;Brien", "David O'Brien"),
    ("Jos&#233; Ruiz", "José Ruiz"),
    ("natalya waston", "Natalya Waston"),
    ("THOMAS SEXTON", "Thomas Sexton"),
    ("MATTHEW O&#39;ROURKE", "Matthew O'Rourke"),
    ("BLAS NUNEZ-NETO", "Blas Nunez-Neto"),
    ("MATTHEW MCDONALD", "Matthew McDonald"),
    ("Amy Mcgreevy", "Amy McGreevy"),
    ("Jean Mcmillan Lang", "Jean McMillan Lang"),
    ("PETER VAN DER BERG", "Peter van der Berg"),
    ("THANH LE", "Thanh Le"),
    ("JOHN R. SMITH JR.", "John R. Smith Jr."),
    ("HENRY FORD III", "Henry Ford III"),
    ("  Ada   Park ", "Ada Park"),
    ("&#201;MILE ZOLA", "Émile Zola"),
    ("ÖZGE ÇELIK", "Özge Çelik"),
])
def test_tidy_name_fixes(raw, want):
    assert tidy_name(raw) == want

@pytest.mark.parametrize("name", [
    "Jaime d'Almeida", "Sha'Day Hart", "Tim Op't Holt", "Benjamin Machlin",
    "Emanuele Macri", "Meredith O'Brien-Weiss", "Kevin McDonald", "Anna DeMarco",
])
def test_tidy_name_leaves_good_names_alone(name):
    assert tidy_name(name) == name

def test_tidy_name_passes_empty_through():
    assert tidy_name(None) is None
    assert tidy_name("") == ""


@pytest.mark.parametrize("raw, want", [
    ("Object-Oriented Design", "objectoriented design"),
    ("O’Brien", "obrien"),
    ("Bouvé", "bouve"),
    ("Master’s Project", "masters project"),
    ("International Study—Argentina", "international studyargentina"),
    ("  CS	3500 ", "cs 3500"),
    ("%_'—", ""),
    ("Programming in C++", "programming in c++"),
    ("C# .NET", "c# net"),
    (None, ""),
])
def test_search_fold(raw, want):
    assert search_fold(raw) == want


def test_search_squash():
    assert search_squash("Object-Oriented Design") == "objectorienteddesign"
