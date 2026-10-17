import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workflow.loudness import normalize_final_audio


class FinalMixTests(unittest.TestCase):
    def test_corrects_quiet_final_mix_without_reencoding_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'quiet.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                            'color=c=blue:s=64x64:r=10:d=4','-f','lavfi','-i',
                            'sine=frequency=440:duration=4','-af','volume=0.03',
                            '-c:v','libx264','-c:a','aac','-shortest',str(path)],check=True)
            def video_hash():
                return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0',
                                       '-c:v','copy','-f','hash','-hash','sha256','-'],
                                      check=True,capture_output=True).stdout
            before = video_hash()
            result = normalize_final_audio(path, {'I':-14,'TP':-2.6,'LRA':11})
            self.assertLessEqual(abs(result['input_i'] + 14),1)
            self.assertLessEqual(result['input_tp'],-2.3)
            self.assertEqual(before,video_hash())


if __name__ == '__main__':
    unittest.main()
