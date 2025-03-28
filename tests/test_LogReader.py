import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from cbl_log_reader import LogReader  # Correct import

class TestLogReader(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_data = {
            "file-to-parse": self.temp_dir,
            "cb-cluster-host": "127.0.0.1",
            "cb-bucket-name": "cbl-log-reader",
            "cb-bucket-user": "Administrator",
            "cb-bucket-user-password": "password",
            "cb-expire": 0,
            "debug": False,
            "file-parse-type": "info|error|debug|verbose|warning"
        }
        self.config_file = os.path.join(self.temp_dir, "config.json")
        with open(self.config_file, "w") as f:
            json.dump(self.config_data, f)
        self.patcher = patch('cbl_log_reader.Cluster')
        self.mock_cluster = self.patcher.start()
        self.mock_bucket = MagicMock()
        self.mock_cluster.return_value.bucket.return_value = self.mock_bucket
        self.mock_collection = MagicMock()
        self.mock_bucket.default_collection.return_value = self.mock_collection

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        self.patcher.stop()

    def test_init_and_config_reading(self):
        reader = LogReader(self.config_file)
        self.assertEqual(reader.cbHost, "127.0.0.1")
        self.assertEqual(reader.file_to_parse, self.temp_dir)
        self.assertEqual(reader.file_parse_type, "info|error|debug|verbose|warning")

    def test_single_file_valid(self):
        log_file = os.path.join(self.temp_dir, "cbl_info.txt")
        with open(log_file, "w") as f:
            f.write("17:24:02.456955| [Sync]: Test log\n")
        self.config_data["file-to-parse"] = log_file
        with open(self.config_file, "w") as f:
            json.dump(self.config_data, f)
        with patch.object(LogReader, 'process_single_file') as mock_process:
            reader = LogReader(self.config_file)
            reader.read_log()
            mock_process.assert_called_once_with(log_file)

    def test_single_file_invalid_name(self):
        log_file = os.path.join(self.temp_dir, "random.txt")
        with open(log_file, "w") as f:
            f.write("17:24:02.456955| [Sync]: Test log\n")
        self.config_data["file-to-parse"] = log_file
        with open(self.config_file, "w") as f:
            json.dump(self.config_data, f)
        with self.assertRaises(SystemExit):
            reader = LogReader(self.config_file)
            reader.read_log()

    def test_directory_with_matching_files(self):
        files = ["cbl_info.txt", "cbl_error.log", "random.txt"]
        for fname in files:
            with open(os.path.join(self.temp_dir, fname), "w") as f:
                f.write("17:24:02.456955| [Sync]: Test log\n")
        with patch.object(LogReader, 'process_single_file') as mock_process:
            reader = LogReader(self.config_file)
            reader.read_log()
            expected_calls = [
                unittest.mock.call(os.path.join(self.temp_dir, "cbl_info.txt")),
                unittest.mock.call(os.path.join(self.temp_dir, "cbl_error.log"))
            ]
            mock_process.assert_has_calls(expected_calls, any_order=True)
            self.assertEqual(mock_process.call_count, 2)

    def test_directory_no_matching_files(self):
        with open(os.path.join(self.temp_dir, "random.txt"), "w") as f:
            f.write("17:24:02.456955| [Sync]: Test log\n")
        with self.assertRaises(SystemExit):
            reader = LogReader(self.config_file)
            reader.read_log()

    def test_process_single_file(self):
        log_file = os.path.join(self.temp_dir, "cbl_info.txt")
        log_line = "17:24:02.456955| [Sync]: Test log"
        with open(log_file, "w") as f:
            f.write(log_line + "\n")
        reader = LogReader(self.config_file)
        reader.log_file_name = log_file
        with patch.object(LogReader, 'bigLineProcecess') as mock_big:
            reader.process_single_file(log_file)
            mock_big.assert_called_once_with(log_line, 1)

    def test_bigLineProcecess_sync(self):
        reader = LogReader(self.config_file)
        log_line = "17:24:02.456955| [Sync]: {15790} State: busy, progress=99.9506%"
        with patch.object(LogReader, 'cbUpsert') as mock_upsert:
            reader.bigLineProcecess(log_line, 1)
            expected_data = {
                "logLine": 1,
                "dt": "17:24:02.456955",
                "fullDate": False,
                "type": "Sync",
                "fileName": reader.log_file_name,
                "replicationId": 15790,
                "state": "busy",
                "progress": 0.999506,  # Expected value
                "rawLog": log_line
            }
            mock_upsert.assert_called_once()
            args, kwargs = mock_upsert.call_args
            actual_data = args[1]
            # Replace assertDictContainsSubset with explicit checks
            for key, value in expected_data.items():
                if key == "progress":
                    self.assertAlmostEqual(actual_data[key], value, places=6)  # Allow float precision
                else:
                    self.assertEqual(actual_data[key], value)

if __name__ == '__main__':
    unittest.main()