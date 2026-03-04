import importlib
import unittest


class SmokeImportTests(unittest.TestCase):
    def test_core_modules_import_without_runtime_secrets(self):
        modules = [
            "botapp.extractors.url_text",
            "botapp.extractors.pdf_text",
            "botapp.extractors.input_resolver",
            "botapp.utils.text",
        ]

        for module in modules:
            with self.subTest(module=module):
                importlib.import_module(module)


if __name__ == "__main__":
    unittest.main()
