"""End-to-end checks on synthetic exports in tests/fixtures/staging (no personal data, no network).

Run: python -m unittest discover tests
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import enrich_tmdb  # noqa: E402
from sources import netflix  # noqa: E402
from sources.common import normalize_rating  # noqa: E402


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=ROOT, capture_output=True, text=True)


def rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Ratings(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(normalize_rating("stars", "5")[:2], ("liked", 1.0))
        self.assertEqual(normalize_rating("stars", "3")[:2], ("neutral", 0.5))
        self.assertEqual(normalize_rating("stars", "1")[:2], ("disliked", 0.0))
        self.assertEqual(normalize_rating("thumbs", "1")[:2], ("disliked", 0.0))
        self.assertEqual(normalize_rating("thumbs", "2")[:2], ("liked", 0.75))
        self.assertEqual(normalize_rating("thumbs", "3")[:2], ("liked", 1.0))

    def test_no_opinion(self):
        for scale, v in [("thumbs", "0"), ("stars", "0"), ("stars", "-1"), ("stars", "-2"), ("stars", "")]:
            self.assertIsNone(normalize_rating(scale, v), (scale, v))


class NetflixTypes(unittest.TestCase):
    def kinds(self, titles):
        header = ["Duration", "Start Time", "Profile Name", "Supplemental Video Type", "Title"]
        data = [dict(zip(header, ["01:00:00", "2026-01-01 00:00:00", "A", "", t])) for t in titles]
        return {v["raw_title"]: v["kind"] for v in netflix.views(data)}

    def test_classification(self):
        k = self.kinds([
            "Arrow: Season 2: Broken Dolls (Episode 3)",
            "Avatar: The Last Airbender: Book 1: The Warriors of Kyoshi (Episode 4)",
            "Sliders: Season 1: \"Pilot\"",
            "Wednesday: Season 1",
            "Arrow",
            "Kill Bill: Vol. 1",
            "Harry Potter and the Deathly Hallows: Part 1",
            "Fear Street Part 1: 1994",
            "John Wick: Chapter 2",
            "Aziz Ansari: Buried Alive (Trailer)",
        ])
        self.assertEqual(k["Arrow: Season 2: Broken Dolls (Episode 3)"], "episode")
        self.assertEqual(k["Avatar: The Last Airbender: Book 1: The Warriors of Kyoshi (Episode 4)"], "episode")
        self.assertEqual(k["Sliders: Season 1: \"Pilot\""], "episode")
        self.assertEqual(k["Wednesday: Season 1"], "episode")
        self.assertEqual(k["Arrow"], "episode")  # bare show name seen in episode titles
        for film in ["Kill Bill: Vol. 1", "Harry Potter and the Deathly Hallows: Part 1", "Fear Street Part 1: 1994",
                     "John Wick: Chapter 2"]:
            self.assertEqual(k[film], "movie", film)
        self.assertEqual(k["Aziz Ansari: Buried Alive (Trailer)"], "extra")

    def test_show_name(self):
        self.assertEqual(netflix.split_episode("Avatar: The Last Airbender: Book 1: The Warriors of Kyoshi"),
                         ("Avatar: The Last Airbender", "Book 1"))
        self.assertEqual(netflix.split_episode("American Horror Story: Murder House: Spooky Little Girl"),
                         ("American Horror Story", "Murder House"))


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        run("scripts/normalize.py", "--staging", "tests/fixtures/staging", "--out", cls.tmp)
        cls.movies = {r["id"]: r for r in rows(cls.tmp / "movies.csv")}

    def test_merges_sources(self):
        m = self.movies["die hard"]
        self.assertEqual(m["sources"], "amazon|netflix")
        self.assertEqual(m["verify_type"], "no")  # Amazon said Movie
        self.assertEqual((m["first_watched"], m["last_watched"]), ("2009-02-01", "2026-01-05"))

    def test_latest_rating_wins(self):
        m = self.movies["die hard"]  # 5 stars in 2013, thumbs down in 2025
        self.assertEqual((m["rating_label"], m["rating_score"]), ("disliked", "0.00"))

    def test_rated_only_title_kept(self):
        m = self.movies["alien 3"]  # "Alien 3: Collector's Edition", rated but never streamed
        self.assertEqual((m["sources"], m["rating_label"], m["verify_type"]), ("netflix", "neutral", "yes"))
        self.assertEqual(m["watch_count"], "0")
        self.assertNotIn("alien", self.movies)  # star -2 = "not seen"

    def test_sampled_and_extras(self):
        extras = {r["title"]: r["reason"] for r in rows(self.tmp / "extras.csv")}
        self.assertIn("sampled", extras["Bo Burnham: Inside"])
        self.assertEqual(extras["Moana Trailer"], "trailer or bonus clip")
        self.assertEqual(extras["Some Film"], "trailer")
        self.assertIn("glass onion a knives out mystery", self.movies)  # short view, but rated

    def test_shows(self):
        shows = {r["show"]: r for r in rows(self.tmp / "tv_shows.csv")}
        self.assertEqual(shows["Futurama"]["rating_label"], "liked")
        self.assertEqual(shows["South Park"]["seasons"], "Season 29")
        self.assertIn("SeaQuest DSV", shows)
        self.assertNotIn("Futurama", {m["title"] for m in self.movies.values()})

    def test_profile_filter(self):
        out = self.tmp / "kris"
        run("scripts/normalize.py", "--staging", "tests/fixtures/staging", "--out", out, "--profile", "Kris")
        got = {r["id"] for r in rows(out / "movies.csv")}
        self.assertIn("despicable me 3", got)
        self.assertNotIn("kill bill vol 1", got)
        self.assertIn("the menu", got)  # Amazon rows have no profile and are kept

    def test_profiles_file(self):
        staging = self.tmp / "staging"
        subprocess.run(["cp", "-r", str(ROOT / "tests/fixtures/staging"), str(staging)], check=True)
        (staging / "profiles.txt").write_text("Michael\n", encoding="utf-8")
        out = self.tmp / "michael"
        run("scripts/normalize.py", "--staging", staging, "--out", out)
        got = {r["id"] for r in rows(out / "movies.csv")}
        self.assertIn("kill bill vol 1", got)
        self.assertNotIn("despicable me 3", got)  # Kris only

    def test_enrich_and_graph(self):
        """Fake TMDB through to the graph: sources merge, ratings and history reach the nodes."""
        fake = {
            ("/search/movie", "Die Hard"): [{"id": 562, "title": "Die Hard", "release_date": "1988-07-15", "vote_count": 12000}],
            ("/search/movie", "Futurama: Into the Wild Green Yonder"): [{"id": 12, "title": "Futurama: Into the Wild Green Yonder", "vote_count": 600}],
            ("/search/tv", "Futurama: Into the Wild Green Yonder"): [],
            ("/search/movie", "Alien 3"): [{"id": 8077, "title": "Alien³", "original_title": "Alien³", "vote_count": 5000}],
            ("/search/tv", "Alien 3"): [],
            ("/search/movie", "Kill Bill: Vol. 1"): [{"id": 24, "title": "Kill Bill: Vol. 1", "vote_count": 17000}],
            ("/search/tv", "Kill Bill: Vol. 1"): [],
            ("/search/movie", "Despicable Me 3"): [{"id": 324852, "title": "Despicable Me 3", "vote_count": 7000}],
            ("/search/tv", "Despicable Me 3"): [],
            ("/search/movie", "Glass Onion: A Knives Out Mystery"): [{"id": 661374, "title": "Glass Onion: A Knives Out Mystery", "vote_count": 6000}],
            ("/search/tv", "Glass Onion: A Knives Out Mystery"): [],
            ("/search/movie", "Fear Street Part 1: 1994"): [{"id": 591273, "title": "Fear Street: 1994", "vote_count": 2500}],
            ("/search/tv", "Fear Street Part 1: 1994"): [],
            ("/search/movie", "The Menu"): [{"id": 593643, "title": "The Menu", "vote_count": 4000}],
        }

        def get(path, **params):
            if path.startswith("/movie/"):
                i = int(path.split("/")[2])
                return {"id": i, "title": f"Film {i}", "release_date": "2000-01-01", "genres": [{"name": "Drama"}],
                        "credits": {"crew": [{"name": "D", "job": "Director", "department": "Directing"}], "cast": []},
                        "keywords": {"keywords": []}, "runtime": 100, "vote_average": 7.0, "vote_count": 10}
            return {"results": fake.get((path, params.get("query")), [])}

        old_get, old_key, argv = enrich_tmdb.get, enrich_tmdb.KEY, sys.argv
        out = self.tmp / "enriched.json"
        sys.argv = ["enrich_tmdb.py", "--input", str(self.tmp / "movies.csv"), "--output", str(out)]
        try:
            enrich_tmdb.get, enrich_tmdb.KEY = get, "test"
            enrich_tmdb.main()
            # A second run reuses every matched title without calling TMDB
            # A second run reuses exact matches; only the guess (Fear Street, a fuzzy match) is looked up again
            calls = []
            enrich_tmdb.get = lambda path, **k: calls.append(k.get("query", path)) or get(path, **k)
            enrich_tmdb.main()
            self.assertEqual([c for c in calls if not c.startswith("/movie/")], ["Fear Street Part 1: 1994"] * 2)
        finally:
            sys.argv, enrich_tmdb.get, enrich_tmdb.KEY = argv, old_get, old_key
        rows_ = {r["id"]: r for r in json.loads(out.read_text(encoding="utf-8"))}
        self.assertTrue(rows_["die hard"]["matched"])
        self.assertEqual(rows_["die hard"]["sources"], ["amazon", "netflix"])
        self.assertTrue(rows_["alien 3"]["matched"])  # TMDB spells it "Alien³"
        self.assertEqual(rows_["alien 3"]["rating_label"], "neutral")
        self.assertTrue(rows_["futurama into the wild green yonder"]["matched"])

        html = self.tmp / "graph.html"
        run("graph/build_graph.py", out, html)
        blob = html.read_text(encoding="utf-8").split('id="movie-data">', 1)[1].split("</script>", 1)[0]
        nodes = {m["title"]: m for m in json.loads(blob)["movies"]}
        die_hard = nodes["Film 562"]
        self.assertEqual(die_hard["my_rating"], "disliked")
        self.assertEqual(die_hard["sources"], ["amazon", "netflix"])
        self.assertEqual(die_hard["id"], "562")


class TvCheck(unittest.TestCase):
    def setUp(self):
        self.old = enrich_tmdb.get

    def tearDown(self):
        enrich_tmdb.get = self.old

    def fake(self, movies, shows):
        def get(path, **params):
            q = params.get("query")
            if path == "/search/movie":
                return {"results": movies.get(q, [])}
            if path == "/search/tv":
                return {"results": shows.get(q, [])}
            return {"id": 1, "title": q, "genres": [], "credits": {"crew": [], "cast": []}, "keywords": {"keywords": []}}
        enrich_tmdb.get = get

    def test_show_beats_obscure_film(self):
        self.fake({"24": [{"id": 5, "title": "24", "vote_count": 3}]},
                  {"24": [{"id": 1973, "name": "24", "vote_count": 3000, "first_air_date": "2001-11-06"}]})
        r = enrich_tmdb.enrich({"id": "24", "title": "24", "verify_type": "yes"})
        self.assertEqual((r["matched"], r["media_type"]), (False, "tv"))

    def test_film_beats_obscure_show(self):
        self.fake({"Alien": [{"id": 348, "title": "Alien", "vote_count": 15000}]},
                  {"Alien": [{"id": 9, "name": "Alien", "vote_count": 2}]})
        r = enrich_tmdb.enrich({"id": "alien", "title": "Alien", "verify_type": "yes"})
        self.assertTrue(r["matched"])

    def test_episode_of_show(self):
        self.fake({}, {"Mystery Science Theater 3000": [{"id": 1952, "name": "Mystery Science Theater 3000", "vote_count": 400}]})
        r = enrich_tmdb.enrich({"id": "x", "title": "Mystery Science Theater 3000: Soultaker", "verify_type": "yes"})
        self.assertEqual(r["media_type"], "tv")

    def test_override_beats_cache(self):
        bad = {"source_title": "Thirteen Ghosts", "title": "Thirteen Erotic Ghosts", "tmdb_id": 27477,
               "matched": True, "status": "fuzzy", "media_type": "movie"}
        cache = {"thirteen ghosts": bad}
        self.assertIsNone(enrich_tmdb.from_cache(cache, {"id": "thirteen ghosts", "title": "Thirteen Ghosts"}))
        good = {**bad, "title": "Thir13en Ghosts", "tmdb_id": 9378, "status": "manual override"}
        hit = enrich_tmdb.from_cache({"thirteen ghosts": good}, {"id": "thirteen ghosts", "title": "Thirteen Ghosts"})
        self.assertEqual(hit["tmdb_id"], 9378)

    def test_thirteen_ghosts_override(self):
        self.fake({"Thir13en Ghosts": [{"id": 9378, "title": "Thir13en Ghosts", "release_date": "2001-10-26", "vote_count": 1500}]}, {})
        r = enrich_tmdb.enrich({"id": "thirteen ghosts", "title": "Thirteen Ghosts", "verify_type": "no"})
        self.assertEqual((r["query"], r["status"]), ("Thir13en Ghosts", "manual override"))

    def test_making_of_rejected(self):
        self.fake({"The Abyss": [{"id": 1, "title": "The Making of 'The Abyss'", "vote_count": 3}]}, {})
        r = enrich_tmdb.enrich({"id": "abyss", "title": "The Abyss", "verify_type": "no"})
        self.assertFalse(r["matched"])

    def test_possessive_exact_beats_fuzzy(self):
        self.fake({"John Carpenter's The Fog": [{"id": 2, "title": "John Carpenter's The Fog Revisited", "vote_count": 5}],
                   "The Fog": [{"id": 790, "title": "The Fog", "vote_count": 1500}]}, {})
        r = enrich_tmdb.enrich({"id": "x", "title": "John Carpenter's The Fog", "verify_type": "no"})
        self.assertTrue(r["status"].startswith("without possessive, exact"), r["status"])

    def test_head_of_colon(self):
        self.fake({"Star Wars": [{"id": 11, "title": "Star Wars", "vote_count": 9000}],
                   "X2": [{"id": 36658, "title": "X2", "vote_count": 9000}]}, {})
        r = enrich_tmdb.enrich({"id": "x", "title": "Star Wars: Episode IX: Something", "verify_type": "no"})
        self.assertFalse(r["matched"])  # a series part is a different film
        r = enrich_tmdb.enrich({"id": "y", "title": "X2: X-Men United", "verify_type": "no"})
        self.assertTrue(r["matched"])

    def test_one_word_prefix_needs_subtitle(self):
        self.fake({"Borat": [{"id": 496, "title": "Borat: Cultural Learnings of America for Make Benefit Glorious Nation of Kazakhstan", "vote_count": 7000}]}, {})
        r = enrich_tmdb.enrich({"id": "borat", "title": "Borat", "verify_type": "no"})
        self.assertTrue(r["matched"])

    def test_no_prefix_match_for_one_word(self):
        self.fake({"Black": [{"id": 284054, "title": "Black Panther", "vote_count": 20000}]}, {})
        r = enrich_tmdb.enrich({"id": "black", "title": "Black", "verify_type": "no"})
        self.assertFalse(r["matched"])

    def test_amazon_movies_not_checked(self):
        self.fake({"24": [{"id": 5, "title": "24", "vote_count": 3}]},
                  {"24": [{"id": 1973, "name": "24", "vote_count": 3000}]})
        r = enrich_tmdb.enrich({"id": "24", "title": "24", "verify_type": "no"})
        self.assertTrue(r["matched"])


class Setup(unittest.TestCase):
    """First-run helpers: the .env key file and copying exports out of Downloads."""

    def setUp(self):
        import local_setup
        self.ls = local_setup
        self.tmp = Path(tempfile.mkdtemp())
        self.fixtures = ROOT / "tests" / "fixtures" / "staging"

    def test_exporter_dates(self):
        """The Prime Video exporter script's default timestamp, 2025-09-28 02:00:24.173, keeps its date."""
        from sources.common import parse_date
        self.assertEqual(parse_date("2025-09-28 02:00:24.173"), "2025-09-28")

    def test_env_file(self):
        env = self.tmp / ".env"
        env.write_text('# keys\nexport ANTHROPIC_API_KEY="abc"\nTMDB_API_KEY=old\n', encoding="utf-8")
        self.ls.save_env("TMDB_API_KEY", "new", env)
        self.assertEqual(self.ls.read_env(env), {"ANTHROPIC_API_KEY": "abc", "TMDB_API_KEY": "new"})

    def test_recognizes_exports(self):
        self.assertEqual(self.ls.provides(self.fixtures / "amazon" / "watch-history.csv"), {("amazon", "views")})
        self.assertEqual(self.ls.provides(self.fixtures / "netflix" / "PlaybackRelatedEvents.csv"), set())
        z = self.tmp / "netflix-report.zip"
        with zipfile.ZipFile(z, "w") as f:
            for name in ("ViewingActivity.csv", "Ratings.csv"):
                f.write(self.fixtures / "netflix" / name, f"CONTENT_INTERACTION/{name}")
        self.assertEqual(self.ls.provides(z), {("netflix", "views"), ("netflix", "ratings")})

    def test_import_newest(self):
        downloads, staging = self.tmp / "Downloads", self.tmp / "data" / "staging"
        downloads.mkdir()
        (downloads / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        old = downloads / "watch-history.csv"
        new = downloads / "watch-history (1).csv"
        shutil.copy(self.fixtures / "amazon" / "watch-history.csv", old)
        shutil.copy(self.fixtures / "amazon" / "watch-history.csv", new)
        with open(new, "a", encoding="utf-8") as f:
            f.write("\n")
        os.utime(old, (1, 1))
        log = []
        self.assertEqual(self.ls.find_exports(downloads, staging, log.append), 1)
        self.assertEqual([p.name for p in (staging / "amazon").iterdir()], [new.name])
        # Running again copies nothing; a newer export replaces the staged one instead of adding to it
        self.assertEqual(self.ls.find_exports(downloads, staging, log.append), 0)
        old.unlink()
        newer = downloads / "watch-history (2).csv"
        shutil.copy(self.fixtures / "amazon" / "watch-history.csv", newer)
        self.assertEqual(self.ls.find_exports(downloads, staging, log.append), 1)
        self.assertEqual([p.name for p in (staging / "amazon").iterdir()], [newer.name])
        self.assertEqual(len(list((self.tmp / "data" / "staging_replaced").rglob("*.csv"))), 1)


class AmazonRequest(unittest.TestCase):
    """Amazon's own data request: Viewing History.csv and Customer Feedback.csv from "Prime Video.zip"."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        src = ROOT / "tests" / "fixtures" / "amazon_request"
        staging = cls.tmp / "staging"
        staging.mkdir()
        with zipfile.ZipFile(staging / "Prime Video.zip", "w") as z:
            z.write(src / "Viewing History.csv", "Your Prime Video Viewing Activity/Viewing History.csv")
            z.write(src / "Customer Feedback.csv", "Your Prime Video Library & Purchases/Customer Feedback.csv")
        run("scripts/normalize.py", "--staging", staging, "--out", cls.tmp / "out")
        cls.movies = {r["title"]: r for r in rows(cls.tmp / "out" / "movies.csv")}
        cls.shows = {r["show"]: r for r in rows(cls.tmp / "out" / "tv_shows.csv")}
        cls.extras = {r["title"]: r for r in rows(cls.tmp / "out" / "extras.csv")}

    def test_episodes(self):
        self.assertEqual(self.shows["Foundation"]["episodes_watched"], "2")
        self.assertIn("Oz", self.shows)
        self.assertIn("Schitt's Creek", self.shows)  # no season, but two different episodes
        self.assertIn("Sea Oak", self.shows)  # "Pilot-"
        self.assertIn("(show name missing in export)", self.shows)  # "Episode 3-Season 1"

    def test_movies(self):
        self.assertEqual(set(self.movies), {"Spider-Man: Homecoming", "Glass", "Tombstone", "Caveat", "The Maiden Heist"})
        self.assertEqual(self.movies["Glass"]["sources"], "amazon")
        self.assertEqual(self.movies["Glass"]["verify_type"], "yes")
        self.assertEqual(self.movies["Spider-Man: Homecoming"]["minutes_watched"], "100")
        self.assertEqual(self.movies["Tombstone"]["first_watched"], "")  # 1990 is a placeholder date

    def test_ratings(self):
        self.assertEqual(self.movies["Glass"]["rating_label"], "liked")
        self.assertEqual(self.movies["Caveat"]["rating_label"], "disliked")  # rated, so kept despite 2 minutes
        self.assertEqual(self.movies["The Maiden Heist"]["type_basis"], "rated on Amazon, not in viewing history")
        self.assertNotIn("Cats", self.movies)  # "Not Interested" is no opinion

    def test_extras(self):
        self.assertIn("The Accountant 2 - Trailer", self.extras)
        self.assertNotIn("Clueless", self.movies)  # Trailer and Promo rows are not views
        self.assertNotIn("Reacher", self.shows)


if __name__ == "__main__":
    unittest.main()
