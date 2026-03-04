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

    def test_extract_from_dom_skips_footer_like_blocks(self):
        html = """
        <main>
          <div class="article-content">
            <h1>Выйти из тени: почему малый и средний бизнес пока осторожничает с ИИ</h1>
            <p>Генеративный ИИ уже проник в офисы, но не в бизнес-планы. Пока руководители размышляют
               о стратегиях, сотрудники потихоньку подписываются на ChatGPT и автоматизируют рутину.</p>
            <p>Компания WMT AI представила обзор ситуации на рынке искусственного интеллекта за 2025 год
               и прогноз на 2026 год. Исследование основано на открытых данных.</p>
          </div>
        </main>
        <div id="footer" class="site-footer">
          <a href="#">Подписаться на рассылку</a>
          <a href="#">Поделиться</a>
          <a href="#">Другие материалы</a>
        </div>
        """

        text = _extract_from_dom(html)

        self.assertIn("Генеративный ИИ уже проник в офисы", text)
        self.assertIn("Компания WMT AI представила обзор", text)
        self.assertNotIn("Подписаться на рассылку", text)

    def test_extract_from_dom_prefers_primary_article_regions(self):
        html = """
        <div class="content-grid">
          <div class="feed-card">
            <p>Короткая заметка.</p>
          </div>
          <div class="feed-card">
            <p>Еще одна короткая заметка.</p>
          </div>
        </div>
        <main>
          <h1>Выйти из тени: почему малый и средний бизнес пока осторожничает с ИИ</h1>
          <p>Генеративный ИИ уже проник в офисы, но не в бизнес-планы. Пока руководители
             размышляют о стратегиях, сотрудники потихоньку подписываются на ChatGPT.</p>
          <p>Компания WMT AI представила обзор ситуации на рынке искусственного интеллекта
             за 2025 год и прогноз на 2026 год. Исследование основано на открытых данных.</p>
          <p>Ключевые выводы показывают переход ИИ в массовый товар и рост прикладных сценариев.</p>
        </main>
        """

        text = _extract_from_dom(html)

        self.assertIn("Выйти из тени", text)
        self.assertIn("Ключевые выводы", text)
        self.assertNotIn("Еще одна короткая заметка", text)

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
