from skill_map.frontmatter import front_matter, kios_source

MARK = "<!-- kios:generated | Quelle: {} | Nicht von Hand aendern - aendere die Quelle und fuehre `kios sync` aus. -->"


def test_keys_values_quotes_and_flow_lists():
    fm = front_matter(b'---\nname: alpha\ndescription: "Does a thing: well"\n'
                      b"title: 'Quoted'\ntags: [runbook, review, git]\nstatus: entwurf\n---\nbody\n")
    assert fm == {"name": "alpha", "description": "Does a thing: well", "title": "Quoted",
                  "tags": ["runbook", "review", "git"], "status": "entwurf"}


def test_block_list_and_crlf():
    fm = front_matter(b"---\r\ntags:\r\n  - a\r\n  - 'b'\r\ncommand: x\r\n---\r\n")
    assert fm == {"tags": ["a", "b"], "command": "x"}


def test_no_front_matter_and_only_the_first_block():
    assert front_matter(b"no front matter\n---\nname: x\n---\n") == {}
    assert front_matter(b"---\nname: a\n---\n---\nname: b\n---\n") == {"name": "a"}


def test_stops_at_the_limit():
    data = b"---\n" + b"x: 1\n" * 2000 + b"name: late\n---\n"
    assert "name" not in front_matter(data, limit=4096)


def test_kios_marker_on_line_1_4_5_and_not_after_2000_bytes():
    one = (MARK.format("templates/k-start.md") + "\n---\ndescription: d\n---\n").encode()
    four = ("---\ndescription: d\n---\n" + MARK.format("40-runbooks/rb-a.md") + "\n").encode()
    five = ("---\ndescription: d\nargument-hint: x\n---\n" + MARK.format("40-runbooks/rb-a.md") + "\n").encode()
    late = ("x" * 2100 + "\n" + MARK.format("40-runbooks/rb-a.md") + "\n").encode()
    assert kios_source(one) == "templates/k-start.md"
    assert kios_source(four) == "40-runbooks/rb-a.md"
    assert kios_source(five) == "40-runbooks/rb-a.md"
    assert kios_source(late) is None
    assert kios_source(b"plain\n") is None
