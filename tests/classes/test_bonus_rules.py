from classes.bonus_rules import parse_bonus_counts


def test_parse_bonus_counts_golf_handles_tokens_and_counts():
    stats = "43 PAR, 23 BIR, 4 BOG, 2 DBB, 1 3rd, 2 BIR3+ and 1 BOFR, 3 EAG"
    counts = parse_bonus_counts("GOLF", stats)
    assert counts == {"BIR3+": 2, "BOFR": 1, "EAG": 3}


def test_parse_bonus_counts_golf_does_not_match_bir3_without_plus():
    stats = "12 PAR, 3 BIR3, 1 EAG"
    counts = parse_bonus_counts("GOLF", stats)
    assert counts == {"EAG": 1}


def test_parse_bonus_counts_golf_ignores_unknown_tokens():
    stats = "1 XYZ, 2 ABC, 1 BOFR"
    counts = parse_bonus_counts("GOLF", stats)
    assert counts == {"BOFR": 1}


def test_parse_bonus_counts_nba_announces_whatever_dk_reports():
    stats = "10 REB, 12 AST, 28 PTS, 1 DDbl, 1 TDbl"
    counts = parse_bonus_counts("NBA", stats)
    assert counts == {"DDbl": 1, "TDbl": 1}


def test_parse_bonus_counts_nba_absent_tokens():
    stats = "10 REB, 12 AST, 28 PTS"
    counts = parse_bonus_counts("NBA", stats)
    assert counts == {}


def test_parse_bonus_counts_mlb_detects_home_run():
    stats = "3 AB, 2 H, 1 HR, 2 RBI, 1 R"
    counts = parse_bonus_counts("MLB", stats)
    assert counts == {"HR": 1}


def test_parse_bonus_counts_mlb_detects_multi_hr():
    stats = "4 AB, 2 HR, 5 RBI, 2 R"
    counts = parse_bonus_counts("MLB", stats)
    assert counts == {"HR": 2}


def test_parse_bonus_counts_mlb_no_hr():
    stats = "3 AB, 2 H, 2 RBI, 1 R"
    counts = parse_bonus_counts("MLB", stats)
    assert counts == {}


def test_parse_bonus_counts_mlb_zero_hr_ignored():
    stats = "3 AB, 0 HR, 1 H"
    counts = parse_bonus_counts("MLB", stats)
    assert counts == {}


def test_parse_bonus_counts_soc_detects_goal():
    stats = "1 G, 2 A, 3 SOG"
    counts = parse_bonus_counts("SOC", stats)
    assert counts == {"G": 1}


def test_parse_bonus_counts_soc_detects_multi_goal():
    stats = "2 G, 1 A"
    counts = parse_bonus_counts("SOC", stats)
    assert counts == {"G": 2}


def test_parse_bonus_counts_soc_zero_goals_ignored():
    stats = "0 G, 1 A, 2 SOG"
    counts = parse_bonus_counts("SOC", stats)
    assert counts == {}


def test_parse_bonus_counts_soc_no_goals():
    stats = "0 A, 3 SOG"
    counts = parse_bonus_counts("SOC", stats)
    assert counts == {}


def test_parse_bonus_counts_soc_sog_not_matched_as_goal():
    stats = "0 G, 0 A, 4 SOG"
    counts = parse_bonus_counts("SOC", stats)
    assert counts == {}


def test_parse_bonus_counts_soc_gk_not_matched_as_goal():
    stats = "1 GK, 3 SOG, 0 G"
    counts = parse_bonus_counts("SOC", stats)
    assert counts == {}
