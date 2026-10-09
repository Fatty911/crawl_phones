import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preserve_publish_baseline import preserve_baseline
from verify_publish_superset import identity_keys, verify_superset


class PreserveIdentityAssociationsTest(unittest.TestCase):
    def row(self, primary, related, model, source="中关村在线+CNMO", brand="OPPO"):
        return {"手机ID": primary, "关联手机ID": related, "型号": model,
                "数据来源": source, "品牌": brand, "上市时间": "2026年5月"}

    def preserve(self, baseline, candidate=None):
        merged, restored = preserve_baseline(copy.deepcopy(baseline), copy.deepcopy(candidate or []))
        verify_superset(baseline, merged)
        expected = {key for row in baseline for key in identity_keys(row)}
        actual = {key for row in merged for key in identity_keys(row)}
        self.assertLessEqual(expected, actual)
        return merged, restored

    def test_cross_associated_different_storage_variants_survive(self):
        rows = [self.row("2002550", "1626958|2002550|2002551", "OPPO K12(12GB/256GB)"),
                self.row("2002551", "1626959|2002550|2002551", "OPPO K12(12GB/512GB)")]
        merged, _ = self.preserve(rows)
        self.assertEqual(len(merged), 2)
        self.assertEqual({row["型号"] for row in merged}, {row["型号"] for row in rows})
        self.assertEqual({row["数据来源"] for row in merged}, {"中关村在线+CNMO"})

    def test_same_variant_dedup_transfers_all_historical_ids(self):
        single = self.row("cnmo", "cnmo|legacy-a|legacy-b", "OPPO K12(12GB+256GB)", "CNMO")
        rich = self.row("zol", "cnmo|zol", "OPPO K12(12GB/256GB)")
        merged, restored = self.preserve([single, rich])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["手机ID"], "zol")
        self.assertEqual(merged[0]["数据来源"], "中关村在线+CNMO")
        self.assertEqual(restored, ["id:zol"])

    def test_different_ram_variants_are_not_conflated(self):
        rows = [self.row("a", "a|b", "OPPO K12(12GB/256GB)"),
                self.row("b", "b|old-b", "OPPO K12(16GB/256GB)")]
        merged, _ = self.preserve(rows)
        self.assertEqual(len(merged), 2)

    def test_full_width_storage_variants_are_distinct(self):
        rows = [self.row("2128105", "2128105|2128360|2641859", "华为nova 14（256GB）", brand="华为"),
                self.row("2128360", "1627511|2128105|2128360", "华为nova 14（512GB）", brand="华为")]
        merged, _ = self.preserve(rows)
        self.assertEqual(len(merged), 2)

    def test_model_level_dedup_keeps_all_list_associations(self):
        rows = [self.row("rich", "rich|a", "OPPO K12", "中关村在线+太平洋电脑网+CNMO"),
                self.row("poor", ["legacy", "poor"], "OPPO K12", "CNMO")]
        merged, _ = self.preserve(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["手机ID"], "rich")
        self.assertEqual(merged[0]["数据来源"], "中关村在线+太平洋电脑网+CNMO")

    def test_association_does_not_cover_other_brand(self):
        rows = [self.row("a", "a|b", "示例机(12GB/256GB)"),
                self.row("b", "b|old-b", "示例机(12GB/256GB)", brand="vivo")]
        merged, _ = self.preserve(rows)
        self.assertEqual(len(merged), 2)

    def test_sparse_unrelated_candidate_keeps_baseline_identities(self):
        rows = [self.row("a", "a|b", "OPPO K12(12GB/256GB)"),
                self.row("b", "old-b|b", "OPPO K12(12GB/512GB)")]
        candidate = [self.row("unrelated", "", "OPPO Find X8", "中关村在线")]
        merged, _ = self.preserve(rows, candidate)
        self.assertEqual(len(merged), 3)

    def test_real_candidate_primary_still_replaces_matching_baseline(self):
        baseline = [self.row("a", "a|b", "OPPO K12(12GB/256GB)"),
                    self.row("b", "b|old-b", "OPPO K12(12GB/512GB)")]
        candidate = [self.row("b", "", "OPPO K12(12GB/512GB)")]
        baseline[0].update({"内存": "12GB", "存储": "256GB"})
        baseline[1].update({"内存": "12GB", "存储": "512GB"})
        candidate[0].update({"内存": "12GB", "存储": "512GB"})
        merged, _ = self.preserve(baseline, candidate)
        self.assertEqual(len(merged), 2)
        self.assertEqual(sum(row["手机ID"] == "b" for row in merged), 1)


if __name__ == "__main__":
    unittest.main()
