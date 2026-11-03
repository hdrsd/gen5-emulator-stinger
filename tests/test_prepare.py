import gzip
import stat
import unittest

from prepare import build_ramdisk, read_newc, write_newc


def record(name, data=b'', mode=stat.S_IFREG | 0o644, crc=False):
    name = name.encode() + b'\0'
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name), 0]
    header = (b'070702' if crc else b'070701') + ''.join(f'{v:08x}' for v in fields).encode()
    return header, name, data


INIT = b'''on fs
    mount yaffs2 mtd@system /system
    mount yaffs2 mtd@system /system ro remount
    mount yaffs2 mtd@userdata /data
    mount yaffs2 mtd@cache /cache
on boot
    setprop example.keep yes
'''


def archive(**kwargs):
    return write_newc([
        record('init.rc', INIT, **kwargs),
        record('default.prop', b'ro.secure=1\nexample.keep=yes\n'),
        record('init', b'example-executable', stat.S_IFREG | 0o750),
        record('sbin/link', b'../init', stat.S_IFLNK | 0o777),
        record('TRAILER!!!'),
    ])


class RamdiskTests(unittest.TestCase):
    def test_only_two_entries_changed_preserving_other_metadata(self):
        original = read_newc(archive())
        result = read_newc(gzip.decompress(build_ramdisk(archive())))
        self.assertEqual(len(original), len(result))
        self.assertEqual(original[2:], result[2:])
        for old, new in zip(original[:2], result[:2]):
            self.assertEqual(old[1], new[1])
            self.assertEqual(old[0][:54], new[0][:54])
            self.assertEqual(old[0][62:], new[0][62:])
        self.assertIn(b'example.keep', result[0][2])
        self.assertIn(b'example.keep', result[1][2])
        self.assertIn(b'-b 127.0.0.1', result[0][2])

    def test_gzip_input_and_crc_archive(self):
        raw = archive(crc=True)
        self.assertEqual(build_ramdisk(raw), build_ramdisk(gzip.compress(raw)))

    def test_already_patched_rejected(self):
        with self.assertRaisesRegex(ValueError, 'already patched'):
            build_ramdisk(build_ramdisk(archive()))

    def test_target_symlink_rejected(self):
        with self.assertRaisesRegex(ValueError, 'regular file'):
            build_ramdisk(archive(mode=stat.S_IFLNK | 0o777))

    def test_traversal_and_duplicates_rejected(self):
        for entries in ([record('../bad')], [record('same'), record('./same')]):
            with self.assertRaises(ValueError):
                read_newc(write_newc(entries + [record('TRAILER!!!')]))

    def test_corruption_and_truncation_rejected(self):
        raw = archive(crc=True)
        for invalid in (raw[:90], raw.replace(b'example.keep yes', b'example.keep bad')):
            with self.assertRaises(ValueError):
                read_newc(invalid)


if __name__ == '__main__':
    unittest.main()
