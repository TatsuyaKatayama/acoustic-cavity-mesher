"""Synthetic ACP subprocesses; no model provider, credentials or real CAD sent."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from b3_acp import ACPClient, ACPError, ACPPermissionRequired, ACPTimeout, run_workflow, validate_config
from b3_test_support import assigned_fixture, box_plan


FAKE = r'''
import json,sys,time
from pathlib import Path
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
mode,log=sys.argv[1:3]
def send(data):
    print(json.dumps({'jsonrpc':'2.0',**data},ensure_ascii=False),flush=True)
for line in sys.stdin:
    m=json.loads(line)
    with open(log,'a',encoding='utf-8') as stream:stream.write(json.dumps(m)+'\n')
    method=m.get('method')
    if method=='initialize':
        send({'id':m['id'],'result':{'protocolVersion':2 if mode=='v2' else 1,'agentCapabilities':{},'agentInfo':{'name':'synthetic-test'}}})
    elif method=='session/new':
        if mode=='auth':send({'id':m['id'],'error':{'code':-32000,'message':'Authentication required'}})
        else:send({'id':m['id'],'result':{'sessionId':'fake-session','models':{'availableModels':[{'modelId':'fake-model[medium]'}]}}})
    elif method=='session/set_model':
        send({'id':m['id'],'result':{}})
    elif method=='session/prompt':
        if mode=='timeout':continue
        if mode=='permission':
            send({'id':500,'method':'session/request_permission','params':{'sessionId':'fake-session','toolCall':{'title':'arbitrary command'},'options':[{'optionId':'all','kind':'allow_always','name':'allow everything'}]}})
            continue
        if mode=='unsupported':
            send({'id':501,'method':'terminal/create','params':{'command':'anything'}})
            continue
        if mode=='malformed':
            print('not-json',flush=True);continue
        prompt=m['params']['prompt'][0]['text']
        if mode=='coordinator':
            answer={'action':'dispatch','part_id':'1/1'} if 'As coordinator, verify' in prompt else {'summary':'collected','next_action':'Human review'}
            if 'As coordinator, collect' in prompt and len(sys.argv)>4:
                target=Path(sys.argv[4]);target.write_bytes(target.read_bytes()+b'TAMPER')
        elif mode=='worker':answer={'plan':json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))}
        elif mode=='worker-fh':answer={'template_id':'fh_casting_trial','parameters':json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')),'rationale':'Synthetic FH routing test'}
        elif mode=='checker':answer={'status':'ok','findings':['Synthetic independent review']}
        else:answer={'message':'面の確認'}
        send({'method':'session/update','params':{'sessionId':'fake-session','update':{'sessionUpdate':'agent_thought_chunk','content':{'type':'text','text':'PRIVATE_THOUGHT_NOT_TO_SAVE'}}}})
        send({'method':'session/update','params':{'sessionId':'fake-session','update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':json.dumps(answer,ensure_ascii=False)}}}})
        send({'id':m['id'],'result':{'stopReason':'end_turn'}})
    elif method=='session/cancel':
        if mode=='timeout':time.sleep(.02)
'''


class ACPTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.script=self.root/'fake.py';self.script.write_text(FAKE,encoding='utf-8')
        self.log=self.root/'messages.jsonl'

    def client(self,mode,timeout=2):
        return ACPClient([sys.executable,str(self.script),mode,str(self.log)],self.root,timeout=timeout)

    def test_initialize_session_text_and_no_client_tools(self):
        with self.client('echo') as client:
            self.assertEqual(client.initialize()['protocolVersion'],1)
            client.new_session(self.root)
            self.assertEqual(client.prompt('面を確認'),{'message':'面の確認'})
            self.assertNotIn('PRIVATE_THOUGHT_NOT_TO_SAVE',json.dumps(client.updates))
        messages=[json.loads(v) for v in self.log.read_text().splitlines()]
        self.assertEqual(messages[0]['params']['clientCapabilities'],{})
        self.assertEqual(messages[1]['params']['mcpServers'],[])
        self.assertEqual(messages[2]['params']['prompt'][0]['type'],'text')

    def test_wrong_protocol_and_auth_errors_are_explicit(self):
        with self.client('v2') as client:
            with self.assertRaisesRegex(ACPError,'v1'):client.initialize()
        with self.client('auth') as client:
            client.initialize()
            with self.assertRaisesRegex(ACPError,'Authentication'):client.new_session(self.root)

    def test_permission_is_cancelled_never_granted(self):
        with self.client('permission') as client:
            client.initialize();client.new_session(self.root)
            with self.assertRaises(ACPPermissionRequired):client.prompt('Do work')
            self.assertEqual(len(client.permissions),1)
        messages=[json.loads(v) for v in self.log.read_text().splitlines()]
        answers=[v for v in messages if v.get('id')==500]
        self.assertEqual(answers[0]['result'],{'outcome':{'outcome':'cancelled'}})
        self.assertTrue(any(v.get('method')=='session/cancel' for v in messages))

    def test_timeout_sends_session_cancel_and_terminates_process(self):
        with self.client('timeout',timeout=.5) as client:
            client.initialize();client.new_session(self.root)
            with self.assertRaises(ACPTimeout):client.prompt('Wait')
        self.assertIsNotNone(client.process.poll())
        messages=[json.loads(v) for v in self.log.read_text().splitlines()]
        self.assertTrue(any(v.get('method')=='session/cancel' for v in messages))

    def test_unsupported_client_capability_and_malformed_stdout_rejected(self):
        for mode in ('unsupported','malformed'):
            with self.client(mode) as client:
                client.initialize();client.new_session(self.root)
                with self.assertRaises(ACPError):client.prompt('Check')

    def test_no_shell_or_implicit_provider(self):
        for argv in ('kiro-cli acp', ['kiro-cli','acp'], []):
            with self.assertRaises(ACPError):ACPClient(argv,self.root)
        config={'schema_version':1,'roles':{r:{'argv':[sys.executable]} for r in ('coordinator','worker','checker')}}
        self.assertEqual(validate_config(config),config)
        invalid=deepcopy(config);invalid['roles']['worker']['shell']=True
        with self.assertRaises(ACPError):validate_config(invalid)

    def test_model_selection_requires_advertised_id(self):
        with self.client('echo') as client:
            client.initialize();session=client.new_session(self.root)
            with self.assertRaises(ACPError):client.select_model(session,'invented')
            self.assertEqual(client.select_model(session,'fake-model[medium]'),{})


class ACPWorkflowTests(unittest.TestCase):
    def setUp(self):
        ACPTransportTests.setUp(self)
        self.fixture,self.workflow,self.task=assigned_fixture(self)
        self.plan=self.root/'plan.json';self.plan.write_text(json.dumps(box_plan()),encoding='utf-8')
        self.config={'schema_version':1,'roles':{r:{'argv':[sys.executable,str(self.script),r,str(self.root/(r+'.jsonl')),str(self.plan)]} for r in ('coordinator','worker','checker')}}

    def test_single_part_agent_workflow_builds_checks_collects(self):
        output=self.workflow/'acp-run'
        result=run_workflow(self.workflow/'task.json',self.config,output,timeout=3)
        self.assertEqual(result['status'],'checked',result)
        self.assertFalse(result['automatic_next_stage'])
        self.assertTrue((output/'attempt-001'/'generated.py').is_file())
        transcript=json.loads((output/'acp-transcript.json').read_text(encoding='utf-8'))
        self.assertEqual([t['role'] for t in transcript],['coordinator','worker','checker','coordinator'])
        self.assertNotIn('PRIVATE_THOUGHT_NOT_TO_SAVE',json.dumps(transcript))

    def test_agent_ok_cannot_override_measured_bad_geometry(self):
        wrong=box_plan(height=1)
        self.plan.write_text(json.dumps(wrong),encoding='utf-8')
        result=run_workflow(self.workflow/'task.json',self.config,self.workflow/'bad',timeout=3)
        self.assertEqual(result['status'],'return_to_worker',result)
        self.assertEqual(result['agent_check'],'ok')
        self.assertEqual(result['geometry_check'],'ng')

    def test_permission_stops_before_worker_or_cad_generation(self):
        self.config['roles']['coordinator']['argv'][2]='permission'
        output=self.workflow/'denied'
        result=run_workflow(self.workflow/'task.json',self.config,output,timeout=3)
        self.assertEqual(result['status'],'permission_required')
        self.assertFalse((output/'attempt-001').exists())
        self.assertTrue((output/'workflow.json').is_file())

    def test_final_coordinator_cannot_mutate_checked_artifact(self):
        output=self.workflow/'tampered'
        self.config['roles']['coordinator']['argv'].append(str(output/'attempt-001'/'final.brep'))
        result=run_workflow(self.workflow/'task.json',self.config,output,timeout=3)
        self.assertEqual(result['status'],'failed',result)
        self.assertIn('final coordinator',result['error'])

    def test_allowlisted_fh_builder_dispatch_cannot_pass_wrong_source_part(self):
        from test_b3_fh import dimensions
        parameters=self.root/'fh-parameters.json'
        parameters.write_text(json.dumps(dimensions()),encoding='utf-8')
        self.config['builder']={'kind':'fh_casting_trial','parameters':str(parameters)}
        self.config['roles']['worker']['argv'][2]='worker-fh'
        self.config['roles']['worker']['argv'][4]=str(parameters)
        output=self.workflow/'wrong-fh'
        result=run_workflow(self.workflow/'task.json',self.config,output,timeout=3)
        self.assertEqual(result['status'],'return_to_worker',result)
        artifact=json.loads((output/'attempt-001'/'artifact.json').read_text(encoding='utf-8'))
        self.assertEqual(artifact['template_id'],'fh_casting_trial')
        transcript=json.loads((output/'acp-transcript.json').read_text(encoding='utf-8'))
        self.assertIn('Initial dimensional proposal',transcript[1]['prompt'])


if __name__=='__main__':unittest.main()
