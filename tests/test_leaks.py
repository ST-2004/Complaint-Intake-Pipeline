from complaint_intake.redaction.leaks import SeededValue, find_leaks


def test_partial_name_counts_once_with_fragments():
    leaks = find_leaks([SeededValue("Person", "Jordan Mitchell")], "Hi [PERSON] Mitchell")
    assert len(leaks) == 1 and leaks[0].fragments == ("Mitchell",)


def test_name_match_is_word_bounded_and_case_insensitive():
    seeded = [SeededValue("Person", "Ana Lee")]
    assert find_leaks(seeded, "Banana sleep") == []
    assert find_leaks(seeded, "hi ana")[0].fragments == ("Ana",)


def test_numbers_match_across_separators():
    seeded = [SeededValue("CreditCardNumber", "4111 1111 1111 1111")]
    assert find_leaks(seeded, "card 4111-1111-1111-1111 declined")
    assert find_leaks(seeded, "card [CARD_NUMBER] declined") == []


def test_other_values_are_substring_matches():
    seeded = [SeededValue("Email", "d.okafor82@example.com")]
    assert find_leaks(seeded, "mail D.Okafor82@Example.com")
    assert find_leaks(seeded, "mail [EMAIL]") == []
