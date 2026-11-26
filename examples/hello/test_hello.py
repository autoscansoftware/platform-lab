import unittest

import hello


class HelloTest(unittest.TestCase):
    def test_info_keys(self):
        data = hello.info()
        self.assertEqual(set(data), {"system", "machine", "python"})
        self.assertTrue(all(data.values()))

    def test_main_returns_zero(self):
        self.assertEqual(hello.main(), 0)


if __name__ == "__main__":
    unittest.main()
