import hashlib
import unittest

from ramlink_mesh.agent import (
    CapacityError, MAX_FRAME, ObjectPool, ProtocolError,
    decode_meta_data, encode_meta_data, pack_frame, HEADER, MAGIC, VERSION,
)


class ObjectPoolTests(unittest.TestCase):
    def test_put_get_and_hash(self):
        pool = ObjectPool(1024)
        result = pool.put("dataset/chunk-1", b"hello")
        data, meta = pool.get("dataset/chunk-1")
        self.assertEqual(data, b"hello")
        self.assertEqual(meta["sha256"], hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(result["size"], 5)
        self.assertEqual(pool.stats()["used_bytes"], 5)

    def test_replace_keeps_accounting_correct(self):
        pool = ObjectPool(16)
        pool.put("x", b"1234")
        pool.put("x", b"123456")
        self.assertEqual(pool.used_bytes, 6)

    def test_capacity_is_enforced(self):
        pool = ObjectPool(4)
        pool.put("x", b"1234")
        with self.assertRaises(CapacityError):
            pool.put("y", b"5")

    def test_missing_key(self):
        with self.assertRaises(KeyError):
            ObjectPool(8).get("missing")

    def test_invalid_key(self):
        with self.assertRaises(ValueError):
            ObjectPool(8).put("../bad\nkey", b"x")


class ProtocolTests(unittest.TestCase):
    def test_metadata_and_raw_bytes_round_trip(self):
        payload = encode_meta_data({"key": "x"}, b"raw\x00bytes")
        meta, data = decode_meta_data(payload)
        self.assertEqual(meta, {"key": "x"})
        self.assertEqual(data, b"raw\x00bytes")

    def test_frame_header_layout(self):
        packed = pack_frame(3, 42, b"abc")
        magic, version, msg_type, size, request_id = HEADER.unpack(packed[:HEADER.size])
        self.assertEqual((magic, version, msg_type, size, request_id),
                         (MAGIC, VERSION, 3, 3, 42))

    def test_oversized_frame_rejected(self):
        with self.assertRaises(ProtocolError):
            pack_frame(3, 1, b"x" * (MAX_FRAME + 1))


if __name__ == "__main__":
    unittest.main()
