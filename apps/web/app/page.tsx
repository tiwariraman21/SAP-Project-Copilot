"use strict";
"use client";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ArtifactView from "./components/ArtifactView";
import CompanionChat from "./components/CompanionChat";
import JiraSyncModal from "./components/JiraSyncModal";
import "./analysis-status.css";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Chunk={id:string;page:number;locator:string;text:string};
type Req={id:string;requirement_key:string;title:string;statement:string;requirement_type:string;priority:string;rationale?:string;acceptance_criteria:string[];assumptions?:string[];source_chunk_ids:string[];source_quote:string;confidence:number;review_status:string};
type Project={id:string;name:string;status:string;filename:string;page_count:number;chunks:Chunk[];requirements:Req[];artifacts:{id:string;kind:string;status:string;payload:any}[]};
type ProcessLog={timestamp:string;level:string;message:string};
type TimingRecord={function:string;duration_ms:number;status:string};
type ProcessingStatus={project_id:string;status:string;stage:string;progress:number;error:string|null;logs:ProcessLog[];timings?:TimingRecord[]};
const steps=["Upload","Extract","Review","Generate"];
const labels:Record<string,string>={fsd:"Functional Specification",backlog:"Backlog & Sprints",technical_design:"Technical Design",test_cases:"Test Cases"};
const priorityLabels:Record<string,string>={must:"Must Have",should:"Good To Have",could:"Nice To Have",wont:"Won't Have","won't":"Won't Have"};

function isProject(value:unknown):value is Project{
 if(!value||typeof value!=="object")return false;
 const candidate=value as Partial<Project>;
 return typeof candidate.id==="string"&&Array.isArray(candidate.requirements)&&Array.isArray(candidate.chunks)&&Array.isArray(candidate.artifacts);
}

async function responseBody(response:Response):Promise<any>{
 const body=await response.json().catch(()=>({detail:`Request failed with status ${response.status}`}));
 if(!response.ok)throw new Error(body?.detail||body?.error||`Request failed with status ${response.status}`);
 return body;
}

async function projectResponse(response:Response):Promise<Project>{
 const body=await responseBody(response);
 if(!isProject(body))throw new Error("The API returned an invalid project response. Check the backend console for details.");
 return body;
}

export default function Home(){
 const [project,setProject]=useState<Project|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[view,setView]=useState<string>("requirements"),[elapsed,setElapsed]=useState(0),[jobId,setJobId]=useState(""),[processStatus,setProcessStatus]=useState<ProcessingStatus|null>(null),[fsdJobId,setFsdJobId]=useState(""),[fsdStatus,setFsdStatus]=useState<ProcessingStatus|null>(null),[artifactStatuses,setArtifactStatuses]=useState<Record<string,ProcessingStatus>>({}),[generationBusy,setGenerationBusy]=useState<Record<string,boolean>>({}),[bulkReviewBusy,setBulkReviewBusy]=useState(false),[starterCodeBusy,setStarterCodeBusy]=useState(false),[resourceBusy,setResourceBusy]=useState(false),[companionOpen,setCompanionOpen]=useState(false),[jiraModalOpen,setJiraModalOpen]=useState(false),[jiraModalMode,setJiraModalMode]=useState<"stories"|"tests">("stories");
 const [editingReq,setEditingReq]=useState<Req|null>(null),[isAddingReq,setIsAddingReq]=useState(false),[reqModalBusy,setReqModalBusy]=useState(false);
 const generationLocks=useRef(new Set<string>());
 const unlockGeneration=(kind:string)=>{generationLocks.current.delete(kind);setGenerationBusy(previous=>({...previous,[kind]:false}))};
 useEffect(()=>{if(!busy){setElapsed(0);return}const started=Date.now();const timer=window.setInterval(()=>setElapsed(Math.floor((Date.now()-started)/1000)),1000);return()=>window.clearInterval(timer)},[busy]);
 useEffect(()=>{const projectId=new URLSearchParams(window.location.search).get("project");if(!projectId)return;setBusy(true);fetch(`${API}/api/projects/${projectId}`).then(projectResponse).then(value=>{setProject(value);if(value.artifacts.find(a=>a.kind==="fsd")?.status==="generating")setFsdJobId(value.id)}).catch(x=>setError(x instanceof Error?x.message:"Project could not be loaded")).finally(()=>setBusy(false))},[]);
 useEffect(()=>{if(!jobId)return;let cancelled=false;let timer:number|undefined;const poll=async()=>{try{const r=await fetch(`${API}/api/projects/${jobId}/processing-status`,{cache:"no-store"});if(!r.ok)throw new Error((await r.json()).detail||"Could not read analysis status");const status:ProcessingStatus=await r.json();if(cancelled)return;setProcessStatus(status);if(status.status==="completed"){const projectResponse=await fetch(`${API}/api/projects/${jobId}`,{cache:"no-store"});if(!projectResponse.ok)throw new Error("Analysis completed but the project could not be loaded");setProject(await projectResponse.json());setBusy(false);setJobId("");window.history.replaceState({},"",`/?project=${jobId}`);return}if(status.status==="failed"||status.status==="unknown"){setError(status.error||"Analysis failed");setBusy(false);setJobId("");return}timer=window.setTimeout(poll,1200)}catch(x){if(cancelled)return;setError(x instanceof Error?x.message:"Could not read analysis status");setBusy(false);setJobId("")}};poll();return()=>{cancelled=true;if(timer)window.clearTimeout(timer)}},[jobId]);
 useEffect(()=>{if(!fsdJobId)return;let cancelled=false;let timer:number|undefined;const poll=async()=>{try{const status=await responseBody(await fetch(`${API}/api/projects/${fsdJobId}/artifacts/fsd/processing-status`,{cache:"no-store"})) as ProcessingStatus;if(cancelled)return;setFsdStatus(status);if(status.status==="completed"){setProject(await projectResponse(await fetch(`${API}/api/projects/${fsdJobId}`,{cache:"no-store"})));setFsdJobId("");unlockGeneration("fsd");return}if(status.status==="failed"||status.status==="unknown"){setError(status.error||"FSD generation failed");setFsdJobId("");unlockGeneration("fsd");return}timer=window.setTimeout(poll,1200)}catch(x){if(cancelled)return;setError(x instanceof Error?x.message:"Could not read FSD status");setFsdJobId("");unlockGeneration("fsd")}};poll();return()=>{cancelled=true;if(timer)window.clearTimeout(timer)}},[fsdJobId]);
 const reviewed=useMemo(()=>project?.requirements?.filter(r=>r.review_status!=="pending").length||0,[project]);
 const approvedCount=useMemo(()=>project?.requirements?.filter(r=>r.review_status==="approved").length||0,[project]);
 async function upload(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError("");setProject(null);setProcessStatus(null);const fd=new FormData(e.currentTarget);try{const r=await fetch(`${API}/api/projects/start`,{method:"POST",body:fd});if(!r.ok)throw new Error((await r.json()).detail||"Analysis could not be started");const body=await r.json();setJobId(body.project_id);setProcessStatus({project_id:body.project_id,status:"processing",stage:"API request accepted",progress:5,error:null,logs:[{timestamp:new Date().toISOString(),level:"info",message:`POST ${API}/api/projects/start → 202 Accepted`}]})}catch(x){setError(x instanceof Error?x.message:"Analysis could not be started");setBusy(false)}}
 async function review(id:string,status:string){try{setError("");setProject(await projectResponse(await fetch(`${API}/api/requirements/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({review_status:status})})))}catch(x){setError(x instanceof Error?x.message:"Requirement review failed")}}
 async function approveAll(){if(!project)return;try{setBulkReviewBusy(true);setError("");setProject(await projectResponse(await fetch(`${API}/api/projects/${project.id}/requirements/approve-all`,{method:"POST"})))}catch(x){setError(x instanceof Error?x.message:"Could not approve all requirements")}finally{setBulkReviewBusy(false)}}
 async function approve(){if(!project)return;try{setError("");const updated=await projectResponse(await fetch(`${API}/api/projects/${project.id}/approve`,{method:"POST"}));setProject(updated);setView("fsd");setFsdStatus({project_id:project.id,status:"processing",stage:"Queued",progress:5,error:null,logs:[{timestamp:new Date().toISOString(),level:"info",message:"FSD generation queued after baseline approval"}]});setFsdJobId(project.id)}catch(x){setError(x instanceof Error?x.message:"Baseline approval failed")}}
 async function generate(kind:string){
  if(!project||generationLocks.current.has(kind))return;
  generationLocks.current.add(kind);setGenerationBusy(previous=>({...previous,[kind]:true}));
  try{
   setError("");setView(kind);
   if(kind==="fsd"){
    setFsdStatus({project_id:project.id,status:"processing",stage:"Queued",progress:5,error:null,logs:[{timestamp:new Date().toISOString(),level:"info",message:"FSD generation requested"}]});
    const updated=await projectResponse(await fetch(`${API}/api/projects/${project.id}/artifacts/fsd/start`,{method:"POST"}));setProject(updated);setFsdJobId(project.id);return;
   }
   const queued={project_id:project.id,status:"processing",stage:kind==="backlog"?"Filling planning template":kind==="test_cases"?"Synthesizing test cases":"Generating",progress:40,error:null,logs:[{timestamp:new Date().toISOString(),level:"info",message:kind==="backlog"?"Mapping approved requirements into the Project Planning Excel template":kind==="test_cases"?"Building quality test pack and traceability matrix":`${labels[kind]||"Artifact"} generation requested`}]} as ProcessingStatus;
   setArtifactStatuses(previous=>({...previous,[kind]:queued}));
   setProject(await projectResponse(await fetch(`${API}/api/projects/${project.id}/artifacts/${kind}`,{method:"POST"})));
   setArtifactStatuses(previous=>({...previous,[kind]:{...queued,status:"completed",stage:"Ready",progress:100}}));
  }catch(x){
   const message=x instanceof Error?x.message:`${labels[kind]||"Artifact"} generation failed`;setError(message);
   setArtifactStatuses(previous=>({...previous,[kind]:{...(previous[kind]||{project_id:project.id,logs:[]}),status:"failed",stage:"Generation failed",progress:100,error:message,logs:[...(previous[kind]?.logs||[]),{timestamp:new Date().toISOString(),level:"error",message}]}}));
  }finally{
   if(kind!=="fsd")unlockGeneration(kind)
  }
 }
 async function generateStarterCode(){if(!project)return;try{setStarterCodeBusy(true);setError("");setProject(await projectResponse(await fetch(`${API}/api/projects/${project.id}/artifacts/technical_design/starter-code`,{method:"POST"})))}catch(x){setError(x instanceof Error?x.message:"Starter-code generation failed")}finally{setStarterCodeBusy(false)}}
 async function suggestResources(){if(!project)return;try{setResourceBusy(true);setError("");setView("backlog");const updated=await projectResponse(await fetch(`${API}/api/projects/${project.id}/artifacts/backlog/resource-distribution`,{method:"POST"}));const people=updated.artifacts.find(a=>a.kind==="backlog")?.payload?.resource_distribution?.people;if(!Array.isArray(people)||!people.length)throw new Error("The resource list was not returned. Restart the API from apps/api, then click Suggest Project Resource Distribution again.");setProject(updated)}catch(x){setError(x instanceof Error?x.message:"Resource distribution suggestion failed")}finally{setResourceBusy(false)}}

 async function saveEditReq(e:FormEvent<HTMLFormElement>){
  e.preventDefault();if(!editingReq)return;setReqModalBusy(true);setError("");
  const fd=new FormData(e.currentTarget);
  const title=String(fd.get("title")||"").trim();
  const statement=String(fd.get("statement")||"").trim();
  const requirement_type=String(fd.get("requirement_type")||"functional");
  const priority=String(fd.get("priority")||"must");
  const rationale=String(fd.get("rationale")||"").trim();
  const criteriaRaw=String(fd.get("acceptance_criteria")||"").trim();
  const criteria=criteriaRaw?criteriaRaw.split("\n").map(s=>s.trim()).filter(Boolean):editingReq.acceptance_criteria;
  try{
   const updated=await projectResponse(await fetch(`${API}/api/requirements/${editingReq.id}`,{
    method:"PATCH",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({title,statement,requirement_type,priority,rationale,acceptance_criteria:criteria.length?criteria:["Requirement criteria verified"]}),
   }));
   setProject(updated);setEditingReq(null);
  }catch(x){setError(x instanceof Error?x.message:"Failed to update requirement")}finally{setReqModalBusy(false)}
 }

 async function saveNewReq(e:FormEvent<HTMLFormElement>){
  e.preventDefault();if(!project)return;setReqModalBusy(true);setError("");
  const fd=new FormData(e.currentTarget);
  const title=String(fd.get("title")||"").trim();
  const statement=String(fd.get("statement")||"").trim();
  const requirement_type=String(fd.get("requirement_type")||"functional");
  const priority=String(fd.get("priority")||"must");
  const rationale=String(fd.get("rationale")||"").trim();
  const criteriaRaw=String(fd.get("acceptance_criteria")||"").trim();
  const criteria=criteriaRaw?criteriaRaw.split("\n").map(s=>s.trim()).filter(Boolean):["Requirement implementation verified"];
  try{
   const updated=await projectResponse(await fetch(`${API}/api/projects/${project.id}/requirements`,{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({title,statement,requirement_type,priority,rationale,acceptance_criteria:criteria,review_status:"approved"}),
   }));
   setProject(updated);setIsAddingReq(false);
  }catch(x){setError(x instanceof Error?x.message:"Failed to add requirement")}finally{setReqModalBusy(false)}
 }

 async function deleteReq(id:string){
  if(!confirm("Are you sure you want to delete this requirement?"))return;
  try{
   setError("");
   const updated=await projectResponse(await fetch(`${API}/api/requirements/${id}`,{method:"DELETE"}));
   setProject(updated);if(editingReq?.id===id)setEditingReq(null);
  }catch(x){setError(x instanceof Error?x.message:"Failed to delete requirement")}
 }

 const source=(req:Req)=>project?.chunks.find(c=>req.source_chunk_ids.includes(c.id));
 return <main>
  <aside>
    <div className="brand"><span>SC</span><div>SAP Copilot<small>Delivery intelligence</small></div></div>
    <nav>{["Overview","Requirement Intelligence","Functional Design","Project Planning","Technical Design","Quality & Testing"].map((x,i)=>{const routes=["overview","requirements","fsd","backlog","technical_design","test_cases"];const target=routes[i];const enabled=i<2||project?.status==="approved";return <button type="button" disabled={!enabled} onClick={()=>enabled&&setView(target)} className={view===target?"active":""} key={x}><b>{String(i+1).padStart(2,"0")}</b>{x}{!enabled&&<em>Locked</em>}</button>})}</nav>
    <div className="secure">Human-in-the-loop<br/><small>Every AI output requires review</small></div>
  </aside>
  <section className="workspace">
    {view==="overview"?<><header><div><p className="eyebrow">PROJECT OVERVIEW</p><h1>Your SAP delivery workspace.</h1></div><div className="headerActions">{project&&<button type="button" className="headerCompanionBtn" onClick={()=>setCompanionOpen(true)} title="Chat with AI Companion (Grounded in BRD)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg><span>AI Companion</span></button>}<div className="live">● System ready</div></div></header><div className="overviewHero"><p className="eyebrow">AI SAP PROJECT COPILOT</p><h2>Build from trusted requirements.</h2><p>Upload a BRD, review source-linked requirements, and approve the baseline before downstream delivery agents use it.</p><button onClick={()=>setView("requirements")}>{project?"Continue requirement review →":"Start with a BRD →"}</button></div><div className="overviewStats"><article><strong>{project?.requirements?.length||0}</strong><span>Requirements found</span></article><article><strong>{reviewed}</strong><span>Human reviewed</span></article><article><strong>{project?.status==="approved"?"Approved":"Draft"}</strong><span>Baseline status</span></article></div><div className="overviewCapabilities">{["Requirement Intelligence","Functional Design","Project Planning","Technical Design","Quality & Testing"].map((name,i)=><article className={i===0?"available":""} key={name}><small>{String(i+2).padStart(2,"0")}</small><h3>{name}</h3><p>{i===0?"Available now":"Unlocks after requirement approval"}</p></article>)}</div></>:view!=="requirements"?<ArtifactView label={labels[view]} artifact={project?.artifacts.find(a=>a.kind===view)} projectId={project?.id} onGenerate={()=>generate(view)} onGenerateStarterCode={view==="technical_design"?generateStarterCode:undefined} onSuggestResources={view==="backlog"?suggestResources:undefined} onOpenJiraSync={(mode?: "stories" | "tests")=>{setJiraModalMode(mode||(view==="test_cases"?"tests":"stories"));setJiraModalOpen(true);}} starterCodeBusy={starterCodeBusy} resourceBusy={resourceBusy} generationBusy={!!generationBusy[view]} processStatus={view==="fsd"?fsdStatus:artifactStatuses[view]||null} error={error}/>:<><header><div><p className="eyebrow">REQUIREMENT INTELLIGENCE</p><h1>From BRD to an approved baseline.</h1></div><div className="headerActions">{project&&<button type="button" className="headerCompanionBtn" onClick={()=>setCompanionOpen(true)} title="Chat with AI Companion (Grounded in BRD)"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg><span>AI Companion</span></button>}<div className="live">● System ready</div></div></header>
    <div className="stepper">{steps.map((s,i)=><div className={(project?i<3:i===0)?"done":""} key={s}><span>{i+1}</span>{s}</div>)}</div>
    {!project?<div className="upload"><div className="uploadCopy"><p className="eyebrow">START A PROJECT</p><h2>Ground every requirement in source evidence.</h2><p>Upload a BRD. The copilot extracts atomic requirements, attaches page-level evidence, and sends each item through human review before downstream agents can use it.</p><div className="trust"><span>✓ Source linked</span><span>✓ Schema validated</span><span>✓ Human approved</span></div></div><form onSubmit={upload}><label>Project name<input name="name" required disabled={busy} placeholder="e.g. S/4HANA Order to Cash"/></label><label className="drop">Drop your BRD here<input name="file" type="file" accept=".pdf,.docx,.txt,.md" required disabled={busy}/><small>PDF, DOCX, TXT · up to 20 MB</small></label><button disabled={busy}>{busy?`${processStatus?.stage||"Starting analysis"}…`:"Analyze BRD →"}</button>{busy&&<div className="analysisPanel" role="status"><div className="analysisHeading"><span className="spinner"/><div><b>{processStatus?.stage||"Starting background worker"}</b><small>Elapsed {Math.floor(elapsed/60)}:{String(elapsed%60).padStart(2,"0")} · Job {jobId?jobId.slice(0,8):"pending"}</small></div><strong>{processStatus?.progress||0}%</strong></div><div className="progressTrack"><span style={{width:`${processStatus?.progress||0}%`}}/></div><div className="processConsole"><div className="consoleTitle"><span>LIVE PROCESS CONSOLE</span><span>● polling API every 1.2s</span></div>{(processStatus?.logs||[]).map((log,i)=><div className={`consoleLine ${log.level}`} key={`${log.timestamp}-${i}`}><time>{new Date(log.timestamp).toLocaleTimeString()}</time><span>{log.message}</span></div>)}</div><small className="keepOpen">Keep this page open. The API is working in the background; do not click Analyze again.</small></div>}{error&&<p className="error banner">{error}</p>}</form></div>:
    <><div className="summary"><div><p className="eyebrow">{project.filename}</p><h2>{project.name}</h2></div><div className="metric"><strong>{project.requirements.length}</strong><span>Requirements</span></div><div className="metric"><strong>{reviewed}/{project.requirements.length}</strong><span>Reviewed</span></div><div className="metric"><strong>{project.page_count}</strong><span>Pages</span></div><div className="reviewActions"><button type="button" className="addReqBtn" disabled={project.status==="approved"||bulkReviewBusy} onClick={()=>setIsAddingReq(true)}>+ Add Requirement</button><button className="approveAll" disabled={project.status==="approved"||bulkReviewBusy||approvedCount===project.requirements.length} onClick={approveAll}>{bulkReviewBusy?"Approving…":approvedCount===project.requirements.length?"All approved ✓":"Approve all requirements"}</button><button className="baseline" disabled={project.status==="approved"||reviewed!==project.requirements.length} onClick={approve}>{project.status==="approved"?"Baseline approved ✓":"Approve baseline & generate FSD"}</button></div></div>
    {error&&<p className="error banner">{error}</p>}
    <div className="requirements">{project.requirements.map(req=>{const chunk=source(req);return <article key={req.id} className={req.review_status}><div className="reqHead"><span>{req.requirement_key}</span><span className="type">{req.requirement_type.replace("_"," ")}</span><span className="confidence">{Math.round(req.confidence*100)}% confidence</span></div><h3>{req.title}</h3><p>{req.statement}</p>{req.rationale&&<p style={{fontSize:"12px",color:"var(--muted)",fontStyle:"italic"}}>Rationale: {req.rationale}</p>}<h4>Acceptance criteria</h4><ul>{req.acceptance_criteria.map(x=><li key={x}>{x}</li>)}</ul><div className="source"><b>Source · {chunk?.locator||"Custom Requirement"}</b><q>{req.source_quote}</q></div><div className="actions"><span>Priority: <b>{priorityLabels[req.priority]||req.priority}</b></span><button type="button" className="modifyBtn" onClick={()=>setEditingReq(req)}>Modify</button><button onClick={()=>review(req.id,"rejected")}>Reject</button><button className="approve" onClick={()=>review(req.id,"approved")}>{req.review_status==="approved"?"Approved ✓":"Approve"}</button></div></article>})}</div>
    {project.status==="approved"&&<div className="downstream"><p className="eyebrow">APPROVED KNOWLEDGE BASE</p><h2>Downstream agent capabilities</h2><p>The baseline is locked. These contracts are ready for the next generation slices.</p><div className="cards">{project.artifacts.filter(a=>a.kind!=="traceability"&&a.kind!=="companion").map(a=><button key={a.kind} disabled={!!generationBusy[a.kind]} onClick={()=>{setView(a.kind);if(a.status!=="generated"&&a.status!=="generating")generate(a.kind)}}><span>↗</span><b>{a.payload.label||labels[a.kind]}</b><small>{generationBusy[a.kind]?"Generating now…":a.status==="generated"?"Generated — open":a.status==="generating"?"Generating now…":a.status==="failed"?"Failed — retry":"Ready to generate"}</small></button>)}</div></div>}</>}</>}
  </section>

  {/* Modify Requirement Modal */}
  {editingReq && (
    <div className="reqModalOverlay" role="dialog" aria-label="Modify Requirement">
      <div className="reqModalContent">
        <div className="reqModalHeader">
          <h3>Modify Requirement · {editingReq.requirement_key}</h3>
          <button type="button" onClick={()=>setEditingReq(null)} aria-label="Close">✕</button>
        </div>
        <form onSubmit={saveEditReq}>
          <div className="reqModalBody">
            <div className="formRow">
              <div className="formGroup">
                <label>Requirement Title</label>
                <input name="title" defaultValue={editingReq.title} required disabled={reqModalBusy} />
              </div>
              <div className="formGroup">
                <label>Type</label>
                <select name="requirement_type" defaultValue={editingReq.requirement_type} disabled={reqModalBusy}>
                  <option value="functional">Functional</option>
                  <option value="non_functional">Non-Functional</option>
                  <option value="integration">Integration</option>
                  <option value="data">Data</option>
                  <option value="security">Security</option>
                  <option value="reporting">Reporting</option>
                </select>
              </div>
            </div>
            <div className="formRow">
              <div className="formGroup">
                <label>Priority</label>
                <select name="priority" defaultValue={editingReq.priority} disabled={reqModalBusy}>
                  <option value="must">Must Have</option>
                  <option value="should">Good To Have</option>
                  <option value="could">Nice To Have</option>
                </select>
              </div>
              <div className="formGroup">
                <label>Rationale</label>
                <input name="rationale" defaultValue={editingReq.rationale||""} placeholder="Business rationale..." disabled={reqModalBusy} />
              </div>
            </div>
            <div className="formGroup">
              <label>Requirement Statement</label>
              <textarea name="statement" defaultValue={editingReq.statement} rows={3} required disabled={reqModalBusy} />
            </div>
            <div className="formGroup">
              <label>Acceptance Criteria (one per line)</label>
              <textarea name="acceptance_criteria" defaultValue={(editingReq.acceptance_criteria||[]).join("\n")} rows={3} disabled={reqModalBusy} />
            </div>
          </div>
          <div className="reqModalFooter">
            <button type="button" className="deleteReqBtn" onClick={()=>deleteReq(editingReq.id)} disabled={reqModalBusy}>Delete</button>
            <button type="button" className="cancelBtn" onClick={()=>setEditingReq(null)} disabled={reqModalBusy}>Cancel</button>
            <button type="submit" className="saveBtn" disabled={reqModalBusy}>{reqModalBusy?"Saving…":"Save Changes"}</button>
          </div>
        </form>
      </div>
    </div>
  )}

  {/* Add New Requirement Modal */}
  {isAddingReq && (
    <div className="reqModalOverlay" role="dialog" aria-label="Add New Requirement">
      <div className="reqModalContent">
        <div className="reqModalHeader">
          <h3>Add New Requirement</h3>
          <button type="button" onClick={()=>setIsAddingReq(false)} aria-label="Close">✕</button>
        </div>
        <form onSubmit={saveNewReq}>
          <div className="reqModalBody">
            <div className="formRow">
              <div className="formGroup">
                <label>Requirement Title</label>
                <input name="title" placeholder="e.g. Automated Email Notification on Rejection" required disabled={reqModalBusy} />
              </div>
              <div className="formGroup">
                <label>Type</label>
                <select name="requirement_type" defaultValue="functional" disabled={reqModalBusy}>
                  <option value="functional">Functional</option>
                  <option value="non_functional">Non-Functional</option>
                  <option value="integration">Integration</option>
                  <option value="data">Data</option>
                  <option value="security">Security</option>
                  <option value="reporting">Reporting</option>
                </select>
              </div>
            </div>
            <div className="formRow">
              <div className="formGroup">
                <label>Priority</label>
                <select name="priority" defaultValue="must" disabled={reqModalBusy}>
                  <option value="must">Must Have</option>
                  <option value="should">Good To Have</option>
                  <option value="could">Nice To Have</option>
                </select>
              </div>
              <div className="formGroup">
                <label>Rationale</label>
                <input name="rationale" placeholder="Why this requirement is needed..." disabled={reqModalBusy} />
              </div>
            </div>
            <div className="formGroup">
              <label>Requirement Statement</label>
              <textarea name="statement" placeholder="The system shall..." rows={3} required disabled={reqModalBusy} />
            </div>
            <div className="formGroup">
              <label>Acceptance Criteria (one per line)</label>
              <textarea name="acceptance_criteria" placeholder="1. Action completes successfully&#10;2. SAP status updated" rows={3} disabled={reqModalBusy} />
            </div>
          </div>
          <div className="reqModalFooter">
            <button type="button" className="cancelBtn" onClick={()=>setIsAddingReq(false)} disabled={reqModalBusy}>Cancel</button>
            <button type="submit" className="saveBtn" disabled={reqModalBusy}>{reqModalBusy?"Adding…":"Add Requirement"}</button>
          </div>
        </form>
      </div>
    </div>
  )}

  {project&&<CompanionChat projectId={project.id} projectName={project.name} open={companionOpen} onOpenChange={setCompanionOpen}/>}
  {project&&<JiraSyncModal projectId={project.id} isOpen={jiraModalOpen} mode={jiraModalMode} onClose={()=>setJiraModalOpen(false)} onSyncComplete={async()=>{try{const r=await fetch(`${API}/api/projects/${project.id}`);if(r.ok)setProject(await r.json())}catch{}}}/>}
 </main>
}
