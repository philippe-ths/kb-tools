import unittest

from kb.wikilinks import parse_wikilinks, resolve_target


class ParseWikilinksTest(unittest.TestCase):
    def test_bare_link(self):
        (link,) = parse_wikilinks("see [[concept-alpha]] here")
        self.assertEqual(link.target, "concept-alpha")
        self.assertIsNone(link.alias)
        self.assertIsNone(link.heading)

    def test_alias_is_split_off(self):
        (link,) = parse_wikilinks("[[concept-beta|the beta alias]]")
        self.assertEqual(link.target, "concept-beta")
        self.assertEqual(link.alias, "the beta alias")

    def test_heading_is_split_off(self):
        (link,) = parse_wikilinks("[[wiki/overview#Themes|map]]")
        self.assertEqual(link.target, "wiki/overview")
        self.assertEqual(link.heading, "Themes")
        self.assertEqual(link.alias, "map")

    def test_explicit_paths(self):
        links = parse_wikilinks("[[wiki/overview]] and [[raw/evidence-a]]")
        self.assertEqual([l.target for l in links], ["wiki/overview", "raw/evidence-a"])

    def test_offsets_round_trip(self):
        text = "x [[concept-alpha]] y"
        (link,) = parse_wikilinks(text)
        self.assertEqual(text[link.start : link.end], "[[concept-alpha]]")

    def test_fenced_code_is_ignored(self):
        text = "real [[a]]\n```\n[[ignored]]\n```\n"
        self.assertEqual([l.target for l in parse_wikilinks(text)], ["a"])

    def test_inline_code_is_ignored(self):
        text = "real [[a]] and `[[ignored]]`"
        self.assertEqual([l.target for l in parse_wikilinks(text)], ["a"])

    def test_empty_link_is_skipped(self):
        self.assertEqual(parse_wikilinks("[[]] [[ ]]"), [])


class ResolveTargetTest(unittest.TestCase):
    known = {"wiki/concept-alpha", "raw/evidence-a", "index", "wiki/overview"}

    def test_bare_resolves_into_wiki(self):
        self.assertEqual(resolve_target("concept-alpha", self.known), "wiki/concept-alpha")

    def test_explicit_wiki_path(self):
        self.assertEqual(resolve_target("wiki/overview", self.known), "wiki/overview")

    def test_raw_path_resolves(self):
        self.assertEqual(resolve_target("raw/evidence-a", self.known), "raw/evidence-a")

    def test_bare_root_fallback(self):
        self.assertEqual(resolve_target("index", self.known), "index")

    def test_unknown_bare_is_missing(self):
        self.assertIsNone(resolve_target("concept-missing", self.known))

    def test_unknown_path_is_missing(self):
        self.assertIsNone(resolve_target("wiki/nope", self.known))


if __name__ == "__main__":
    unittest.main()
