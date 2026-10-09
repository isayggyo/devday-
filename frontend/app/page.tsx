'use client';
import {useCallback,useState,useRef} from 'react';
import {BackendStatus} from '../components/backend-status';
import {SessionManager,type LectureSession} from '../components/session-manager';
import {Materials} from '../components/materials';
import {AudioRecorder} from '../components/audio-recorder';
import {LiveNotes} from '../components/live-notes';
import {Questions} from '../components/questions';
import {Mic,AudioLines,Plus,Search} from 'lucide-react';
import {readJson} from '../lib/api';
import {OctiMascot} from '../components/octi-mascot';

type Tab='record'|'materials'|'questions'|'slides';
export default function Page(){
 const [search,setSearch]=useState('');
 const [entry,setEntry]=useState<'record'|'upload'>('record'),[starting,setStarting]=useState(false),[autoStart,setAutoStart]=useState(false);
 const [capturing,setCapturing]=useState(false);
 const [session,setSession]=useState<LectureSession|null>(null);
 const [home,setHome]=useState(true),[tab,setTab]=useState<Tab>('record'),[notice,setNotice]=useState('');
 const selectedRef=useRef(session);selectedRef.current=session;
 const updateSession=useCallback((item:LectureSession)=>setSession(item),[]);
 const selectSession=useCallback((item:LectureSession)=>{
  if(selectedRef.current?.status==='recording'&&item.id!==selectedRef.current.id){setNotice('현재 녹음을 먼저 중지한 뒤 다른 강의를 열어 주세요.');return;}
  setSession(item);setHome(false);setNotice('');
 },[]);
 async function begin(){if(starting)return;if(capturing){setHome(false);return;}setStarting(true);setNotice('');try{const item=await readJson<LectureSession>(await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'새 강의'})}));setAutoStart(entry==='record');setSession(item);setTab(entry==='record'?'record':'materials');setHome(false);}catch(error){setNotice(error instanceof Error?error.message:'강의를 시작하지 못했어요.');}finally{setStarting(false);}}
 const prepared=useCallback((id:string)=>setSession(previous=>previous?.id===id?{...previous,status:'preparing'}:previous),[]);
 return <div className="octi-app" data-testid="lecture-app">
  <aside className="octi-sidebar"><button className="octi-wordmark" onClick={()=>setHome(true)}>Octi</button><label className="octi-search"><Search size={18}/><input placeholder="검색" aria-label="세션 검색" value={search} onChange={event=>setSearch(event.target.value)}/></label><button className="octi-new" onClick={()=>setHome(true)}><Plus size={18}/>새 녹음</button><SessionManager search={search} compact locked={capturing} selected={session} onSelect={selectSession}/><a className="octi-preview-link" href="/preview">화면 연출 미리보기</a><details className="octi-backend"><summary>연결 상태</summary><BackendStatus/></details></aside>
  <main className="octi-main">
   <header hidden={home} className="octi-header"><span>{home?'나의 학습 공간':session?.title}</span><nav aria-label="워크스페이스 탭">{([['record','강의 녹음'],['materials','자료 업로드'],['questions','질문·대화'],['slides','요약 슬라이드']] as const).map(([value,label])=><button key={value} aria-pressed={!home&&tab===value} onClick={()=>{setTab(value);if(session)setHome(false)}}>{label}</button>)}</nav></header>
   {!home&&notice&&<p role="status">{notice}</p>}
   {home&&<section className="octi-home"><div className="entry-tabs" role="tablist" aria-label="강의 시작 방식"><button role="tab" aria-selected={entry==='record'} onClick={()=>setEntry('record')}>강의 녹음</button><button role="tab" aria-selected={entry==='upload'} onClick={()=>setEntry('upload')}>파일 업로드</button></div><div className="intro direct-intro"><OctiMascot/><h1>강의를 들으며, 궁금한 순간 바로 질문하세요.</h1><div className="record-launch"><div className="record-launch-copy"><AudioLines size={23}/><span><strong>{entry==='record'?'새 강의 기록':'강의자료 업로드'}</strong><small>{entry==='record'?'실시간 요약 · 강의 맥락에 맞춘 답변':'PDF · PPT · PPTX'}</small></span></div><button className="primary" disabled={starting} onClick={()=>void begin()}>{entry==='record'&&<Mic size={18}/>} {starting?'준비 중…':entry==='record'?'녹음 시작':'업로드'}</button></div><p className="hint">{entry==='record'?'강의를 들으며 옥티와 함께 기록해 보세요.':'파일을 올려 강의 맥락에 맞게 질문하세요.'}</p>{notice&&<p role="alert">{notice}</p>}</div></section>}
   <div className="octi-content" hidden={home}>
    <div hidden={tab!=='record'}><AudioRecorder key={'audio-'+(session?.id??'none')} session={session} onSession={updateSession} onCaptureActive={setCapturing} autoStart={autoStart}/>{session&&<LiveNotes key={'notes-'+session.id} sessionId={session.id}/>}</div>
    <div hidden={tab!=='materials'}><Materials key={'materials-'+(session?.id??'none')} session={session} onPrepared={prepared}/></div>
    <div className="octi-chat" hidden={tab!=='questions'}>{session&&<Questions key={'questions-'+session.id} sessionId={session.id}/>}</div>
    <div hidden={tab!=='slides'}><section aria-label="생성된 슬라이드"><OctiMascot/><h2>강의의 흐름을 한눈에</h2><p>전체 요약 슬라이드 생성은 아직 연결되지 않았어요.</p><a href="/preview">옥티 로딩과 슬라이드 연출 미리보기</a></section></div>
   </div>
  </main>
 </div>;
}
