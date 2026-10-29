import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

from wzl_blackbox import native_control as control


class EventDispatchTests(unittest.TestCase):
    def test_fixed_event_profile_is_public_beside_legacy_contracts(self):
        self.assertIn('m2-event-evidence', control.COMMANDS)
        self.assertTrue({'window-action','game-input','m2-reload'}.issubset(control.COMMANDS))

    def test_event_evidence_has_its_own_readonly_adapter(self):
        request={'schemaVersion':1,'command':'m2-event-evidence','arguments':{'profile':'custom-monster-summon-v1'}}
        module=SimpleNamespace(validate_request=Mock(return_value={}),run_evidence=Mock(return_value={'readOnly':True}))
        with patch.dict(sys.modules,{'wzl_blackbox.native_events':module}):
            result=control.run(request)
        self.assertEqual(result,{'readOnly':True})
        module.validate_request.assert_called_once_with(request)
        module.run_evidence.assert_called_once_with(request)

    def test_capabilities_disclose_fixed_scope_and_no_arbitrary_memory(self):
        stream=io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(control.main(['capabilities']),0)
        result=json.loads(stream.getvalue())
        self.assertEqual(result['version'],'1.1.24')
        successor=result['delphiEventEvidence']['fixedSharedSuccessor']
        self.assertEqual(successor['rva'],0xFD1F30)
        self.assertEqual(successor['snippetBytes'],512)
        self.assertEqual(result['delphiEventEvidence']['profile'],'custom-monster-summon-v1')
        self.assertFalse(result['delphiEventEvidence']['arbitraryMemoryAccess'])
        self.assertFalse(result['delphiEventEvidence']['processMemoryWrites'])
        self.assertEqual(result['delphiEventEvidence']['analysisCarrierFormat'],'PE32+ AMD64 DLL for static analysis')
        self.assertFalse(result['delphiEventEvidence']['targetExecutionPerformed'])

    def test_event_cli_receipt_cannot_overwrite_an_existing_file(self):
        request={'schemaVersion':1,'command':'m2-event-evidence','arguments':{}}
        with tempfile.TemporaryDirectory() as directory:
            receipt=Path(directory)/'receipt.json'
            receipt.write_bytes(b'preserve-existing-evidence')
            stream=io.StringIO()
            with patch.object(control,'run',return_value={'outputRoot':directory}), patch.object(sys,'stdin',io.StringIO(json.dumps(request))), redirect_stdout(stream):
                result=control.main(['run','--request','-'])
            self.assertEqual(result,1)
            self.assertEqual(receipt.read_bytes(),b'preserve-existing-evidence')


if __name__=='__main__': unittest.main()
