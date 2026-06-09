import unittest

from agents.vision import (
    VisionInputError,
    build_vision_prompt,
    compose_agent_message,
    normalize_scan_type,
    redact_sensitive_text,
    validate_image_upload,
)


class VisionAdapterTests(unittest.TestCase):
    def test_normalize_scan_type_accepts_supported_values(self):
        self.assertEqual(normalize_scan_type(" report "), "report")
        self.assertEqual(normalize_scan_type("DRUG_BOX"), "drug_box")
        self.assertEqual(normalize_scan_type("trace_code"), "trace_code")

    def test_normalize_scan_type_rejects_unknown_value(self):
        with self.assertRaises(VisionInputError):
            normalize_scan_type("avatar")

    def test_validate_image_upload_rejects_unsafe_inputs(self):
        with self.assertRaises(VisionInputError):
            validate_image_upload("application/pdf", 1024)
        with self.assertRaises(VisionInputError):
            validate_image_upload("image/png", 0)
        with self.assertRaises(VisionInputError):
            validate_image_upload("image/png", 8 * 1024 * 1024 + 1)

    def test_report_prompt_forbids_personal_identity_output(self):
        prompt = build_vision_prompt("report")

        self.assertIn("不要提取或输出姓名", prompt)
        self.assertIn("身份证号", prompt)
        self.assertIn("已隐藏", prompt)
        self.assertIn("不要诊断疾病", prompt)

    def test_redact_sensitive_text_removes_common_pii(self):
        raw = "姓名：张三\n手机号：13800138000\n身份证号：110105199001011234\n白细胞：11.2"

        redacted = redact_sensitive_text(raw)

        self.assertIn("姓名：已隐藏", redacted)
        self.assertIn("手机号：已隐藏", redacted)
        self.assertIn("身份证号：已隐藏", redacted)
        self.assertIn("白细胞：11.2", redacted)
        self.assertNotIn("张三", redacted)
        self.assertNotIn("13800138000", redacted)
        self.assertNotIn("110105199001011234", redacted)

    def test_compose_report_message_marks_identity_hidden(self):
        message = compose_agent_message("report", "姓名：李四\n白细胞：偏高")

        self.assertIn("个人身份信息已隐藏", message)
        self.assertIn("姓名：已隐藏", message)
        self.assertIn("请基于以上内容进行报告解读", message)

    def test_compose_drug_box_message_routes_to_pharmacy_context(self):
        message = compose_agent_message("drug_box", "药品名称：布洛芬缓释胶囊")

        self.assertIn("用户上传了一张药盒图片", message)
        self.assertIn("禁忌", message)


if __name__ == "__main__":
    unittest.main()
