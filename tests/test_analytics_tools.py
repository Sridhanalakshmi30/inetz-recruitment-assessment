import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from inetz.analytics import powerbi_embed_url, practice_engine, run_query, verify_practice_account


class GrantConnection:
    def __init__(self, grants, database='inetz_analytics_practice'):
        self.grants, self.database = grants, database

    def exec_driver_sql(self, query):
        if query == 'SELECT DATABASE()':
            return self
        return [(grant,) for grant in self.grants]

    def scalar(self):
        return self.database


class AnalyticsSecurityTests(unittest.TestCase):
    def test_only_exercise_select_account_is_accepted(self):
        verify_practice_account(GrantConnection([
            'GRANT USAGE ON *.* TO `reader`@`127.0.0.1`',
            'GRANT SELECT ON `inetz_analytics_practice`.* TO `reader`@`127.0.0.1`']))

    def test_broad_accounts_and_wrong_database_rejected(self):
        grants = [
            'GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost`',
            'GRANT SELECT, INSERT ON `inetz_analytics_practice`.* TO `reader`@`localhost`',
            'GRANT SELECT ON `inetz_recruitment`.* TO `reader`@`localhost`',
            'GRANT `admin_role`@`%` TO `reader`@`localhost`',
            'GRANT SELECT ON `inetz_analytics_practice`.* TO `reader`@`localhost` WITH GRANT OPTION',
        ]
        for grant in grants:
            with self.subTest(grant=grant), self.assertRaises(HTTPException):
                verify_practice_account(GrantConnection([grant]))
        with self.assertRaises(HTTPException):
            verify_practice_account(GrantConnection([], 'inetz_recruitment'))

    def test_unsafe_sql_is_rejected_before_connecting(self):
        for sql in ['DELETE FROM employees', 'SELECT 1; DROP TABLE employees',
                    'SELECT SLEEP(20)', 'SELECT LOAD_FILE("x")', 'SELECT @password',
                    'SELECT 1 INTO OUTFILE "x"', 'SELECT /* bypass */ 1']:
            with self.subTest(sql=sql), self.assertRaises(HTTPException):
                run_query(sql)

    def test_missing_config_never_uses_recruitment_credentials(self):
        practice_engine.cache_clear()
        with patch.dict(os.environ, {'ANALYTICS_DATABASE_URL': ''}), self.assertRaises(HTTPException) as context:
            run_query('SELECT 1')
        self.assertEqual(context.exception.status_code, 503)

    def test_secure_powerbi_urls_only(self):
        for url in ['http://app.powerbi.com/reportEmbed', 'https://evil.example/reportEmbed',
                    'https://app.powerbi.com/view?r=public']:
            with patch.dict(os.environ, {'POWERBI_EMBED_URL': url}):
                self.assertIsNone(powerbi_embed_url())
        url = 'https://app.powerbi.com/reportEmbed?reportId=123'
        with patch.dict(os.environ, {'POWERBI_EMBED_URL': url}):
            self.assertEqual(powerbi_embed_url(), url)


if __name__ == '__main__':
    unittest.main()
