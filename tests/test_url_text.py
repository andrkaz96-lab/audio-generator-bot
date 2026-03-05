import unittest

from botapp.extractors.url_text import _extract_from_dom, _extract_from_json_ld


class UrlTextExtractionTests(unittest.TestCase):
    def test_extract_from_dom_prefers_article_container(self):
        html = """
        <div class='promo'>Купить подписку прямо сейчас</div>
        <article>
            <h1>Технологии ИИ в 2025 году</h1>
            <p>Это основной текст статьи.</p>
            <p>Здесь еще несколько абзацев с полезной информацией.</p>
        </article>
        <footer>Реклама и служебные ссылки</footer>
        """

        text = _extract_from_dom(html)

        self.assertIn("Технологии ИИ в 2025 году", text)
        self.assertIn("основной текст статьи", text)
        self.assertNotIn("Купить подписку", text)
        self.assertNotIn("Реклама и служебные", text)


    def test_extract_from_dom_prefers_long_article_over_boilerplate_block(self):
        html = """
        <main>
            <p>Компания WMT AI представила обзор ситуации на рынке искусственного интеллекта за 2025 год и прогноз на 2026 год.</p>
            <p>Исследование основано на открытых данных и анализе глобальных и российских тенденций внедрения ИИ.</p>
            <p>Главным трендом стало превращение ИИ в массовый товар, где важна не только точность моделей, но и доступность решений.</p>
        </main>
        <section class='footer-content'>
            Политика конфиденциальности, cookies, подписка, реклама и служебная информация сайта.
        </section>
        """

        text = _extract_from_dom(html)

        self.assertIn("Компания WMT AI представила обзор", text)
        self.assertNotIn("Политика конфиденциальности", text)

    def test_extract_from_json_ld_reads_article_body(self):
        html = """
        <html><head>
        <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "NewsArticle",
                "headline": "Заголовок",
                "articleBody": "Первый абзац. Второй абзац. Третий абзац."
            }
        </script>
        </head><body></body></html>
        """

        text = _extract_from_json_ld(html)

        self.assertEqual(text, "Первый абзац. Второй абзац. Третий абзац.")


if __name__ == "__main__":
    unittest.main()
