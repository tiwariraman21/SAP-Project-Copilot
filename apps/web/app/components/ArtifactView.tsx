"use client";

import { useEffect, useState } from "react";

type Artifact={kind:string;status:string;payload:any};
type ProcessLog={timestamp:string;level:string;message:string};
type TimingRecord={function:string;duration_ms:number;status:string};
type ProcessingStatus={status:string;stage:string;progress:number;error:string|null;logs:ProcessLog[];timings?:TimingRecord[]};
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";

function FlowDiagrams({document}:{document:any}){
 const steps=Array.isArray(document?.process_steps)?document.process_steps.slice(0,12):[];
 const screens=Array.isArray(document?.screens)?document.screens.slice(0,4):[];
 if(!steps.length&&!screens.length)return null;
 return <section className="flowGallery"><div className="flowIntro"><p className="eyebrow">VISUAL DESIGN</p><h3>Process and screen flows</h3><p>Generated from the approved, source-linked requirement baseline.</p></div>{steps.length>0&&<article className="flowDiagram"><div className="diagramHeading"><span>01</span><div><h3>Future-state process flow</h3><p>{steps.length} grounded process steps</p></div></div><div className="processFlow">{steps.map((step:any,index:number)=><div className="flowNodeWrap" key={step.step_id||index}><div className="flowNode"><small>{step.step_id||`STEP-${index+1}`} · {step.actor||"Actor TBD"}</small><strong>{step.activity||step.system_behavior||"Process step"}</strong>{step.decision_or_rule&&step.decision_or_rule!=="TBD"&&<em>Decision: {step.decision_or_rule}</em>}<span>{step.outcome||step.system_behavior}</span></div>{index<steps.length-1&&<div className="flowArrow"><i>↓</i></div>}</div>)}</div></article>}{screens.length>0&&<article className="flowDiagram"><div className="diagramHeading"><span>02</span><div><h3>Screen navigation</h3><p>{screens.length} generated screens</p></div></div><div className="screenFlow">{screens.map((screen:any,index:number)=><div className="screenNodeWrap" key={screen.screen_id||index}><div className="screenNode"><small>{screen.screen_id||`SCREEN-${index+1}`}</small><strong>{screen.name||"Screen"}</strong><span>{screen.purpose||"Purpose TBD"}</span><em>{Array.isArray(screen.roles)?screen.roles.join(" · "):screen.roles}</em></div>{index<screens.length-1&&<div className="screenArrow">→</div>}</div>)}</div></article>}</section>
}

function TimingPanel({items}:{items:TimingRecord[]}){
 if(!items.length)return null;
 const total=items.reduce((sum,item)=>sum+item.duration_ms,0);
 return <section className="timingPanel"><div><p className="eyebrow">FUNCTION TIMING</p><h3>Where generation time is spent</h3><small>{items.length} measured operations · cumulative {(total/1000).toFixed(2)}s</small></div><div className="timingRows">{items.map((item,index)=><div className={item.status} key={`${item.function}-${index}`}><span>{item.function}</span><b>{(item.duration_ms/1000).toFixed(2)}s</b></div>)}</div></section>
}

function FsdPreview({document,validation}:{document:any;validation:any}){
 const requirements=Array.isArray(document?.requirements)?document.requirements:[];
 const screens=Array.isArray(document?.screens)?document.screens:[];
 return <div className="fsdPreview"><section><p className="eyebrow">FIXED FSD V2 STRUCTURE</p><h3>Grounded functional design summary</h3><p>{document?.purpose}</p><div className="previewMetrics"><span><b>{requirements.length}</b> requirements</span><span><b>{screens.length}</b> Fiori screens</span><span><b>{document?.test_conditions?.length||0}</b> tests</span></div></section><section><h3>Requirement catalogue preview</h3><div className="previewTable">{requirements.slice(0,20).map((item:any)=><article key={item.requirement_id}><b>{item.requirement_id}</b><span>{item.title}</span><small>{({must:"Must Have",should:"Good To Have",could:"Nice To Have"} as Record<string,string>)[String(item.priority||"").toLowerCase()]||item.priority} · source preserved</small></article>)}</div>{requirements.length>20&&<p className="previewNote">Showing 20 of {requirements.length}. The DOCX and PDF downloads contain complete coverage and traceability.</p>}</section>{validation?.metrics&&<section><h3>Grounding checks</h3><pre>{JSON.stringify(validation.metrics,null,2)}</pre></section>}</div>
}

function Field({name,value}:{name:string;value:any}){
 if(value===null||value===undefined)return null;
 const label=name.replaceAll("_"," ");
 if(Array.isArray(value)){
  if(!value.length)return <div className="artifactField"><h4>{label}</h4><p>None</p></div>;
  if(value.every(x=>typeof x==="string"))return <div className="artifactField"><h4>{label}</h4><ul>{value.map((x,i)=><li key={i}>{x}</li>)}</ul></div>;
  return <div className="artifactField wide"><h4>{label}</h4><div className="artifactItems">{value.map((x,i)=><article key={i}>{Object.entries(x).map(([k,v])=><Field key={k} name={k} value={v}/>)}</article>)}</div></div>;
 }
 if(typeof value==="object")return <div className="artifactField wide"><h4>{label}</h4><div className="artifactGroup">{Object.entries(value).map(([k,v])=><Field key={k} name={k} value={v}/>)}</div></div>;
 return <div className="artifactField"><h4>{label}</h4><p>{String(value)}</p></div>;
}

function ResourcePreview({distribution,onDownload,downloading}:{distribution:any;onDownload?:()=>void;downloading?:boolean}){
 const summary=Array.isArray(distribution?.summary)?distribution.summary:[];
 const people=Array.isArray(distribution?.people)?distribution.people:[];
 if(!distribution)return null;
 return <section className="resourcePreview" id="resource-distribution">
  <p className="eyebrow">SUGGESTED RESOURCE DISTRIBUTION</p>
  <h3>{distribution.total_resources||people.length} people for {distribution.project_name||"this project"}</h3>
  <p>{distribution.basis||"Suggested from the approved requirement baseline."}</p>
  {onDownload&&<button type="button" className="downloadButton" disabled={!!downloading} onClick={onDownload}>{downloading?"Preparing Excel…":"↓ Download Resource Distribution Excel"}</button>}
  {!!summary.length&&<div className="resourceRoles">{summary.map((item:any)=><span key={item.role}><b>{item.count}</b> {item.role}</span>)}</div>}
  {people.length?<div className="resourcePeople">{people.map((item:any)=><article key={item.label}><b>{item.label}</b><em>{item.level}</em><small>{item.role} · {item.experience}</small></article>)}</div>:<p>No named people were returned. Try Suggest Project Resource Distribution again.</p>}
 </section>;
}

function BacklogPreview({document,resources,jiraSync,onDownloadResources,onOpenJiraSync,downloading}:{document:any;resources?:any;jiraSync?:any;onDownloadResources?:()=>void;onOpenJiraSync?:()=>void;downloading?:boolean}){
 const stories=Array.isArray(document?.stories)?document.stories:[];
 const sprints=Array.isArray(document?.sprints)?document.sprints:[];
 return <div className="fsdPreview">
  {jiraSync&&<div className="jiraSyncBanner" style={{background:"#f0fdf4",border:"1px solid #bbf7d0",borderRadius:"10px",padding:"0.875rem 1.25rem",marginBottom:"1.25rem",display:"flex",justifyContent:"space-between",alignItems:"center"}}><div style={{display:"flex",alignItems:"center",gap:"0.75rem"}}><span style={{fontSize:"1.25rem"}}>🔗</span><div><strong style={{color:"#15803d",fontSize:"0.9375rem"}}>Jira Cloud Synchronized ({jiraSync.project_key})</strong><p style={{margin:0,fontSize:"0.8125rem",color:"#475569"}}>Synced {jiraSync.stories_synced} user stories across {jiraSync.sprints_synced} sprints {jiraSync.epic_key?`under Epic ${jiraSync.epic_key}`:""}</p></div></div>{jiraSync.board_url&&<a href={jiraSync.board_url} target="_blank" rel="noreferrer" style={{background:"#0052cc",color:"#fff",padding:"0.4rem 0.875rem",borderRadius:"6px",fontSize:"0.8125rem",fontWeight:600,textDecoration:"none"}}>Open Jira Board ↗</a>}</div>}
  <ResourcePreview distribution={resources} onDownload={onDownloadResources} downloading={downloading}/>
  <section><div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}><p className="eyebrow">PROJECT PLANNING TEMPLATE</p>{onOpenJiraSync&&<button type="button" onClick={onOpenJiraSync} style={{background:"#0052cc",color:"#ffffff",border:"none",borderRadius:"6px",padding:"0.45rem 0.9rem",fontSize:"0.8125rem",fontWeight:600,cursor:"pointer",display:"flex",alignItems:"center",gap:"0.4rem"}}><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M11.53 2c0 2.4 1.97 4.35 4.35 4.35h1.78v1.7c0 2.4 1.94 4.34 4.34 4.35V2h-10.47zM6.77 6.8c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V6.8H6.77zM2 11.6c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V11.6H2z"/></svg>Sync / Export to Jira</button>}</div><h3>Tasks mapped into the Excel plan</h3><p>Approved requirements were written into the Project Plan sheet. Dashboard, lists, and the progress curve stay formula-driven.</p><div className="previewMetrics"><span><b>{stories.length}</b> tasks</span><span><b>{sprints.length||new Set(stories.map((item:any)=>item.sprint).filter(Boolean)).size}</b> sprints</span></div></section>
  <section><h3>Task preview</h3><div className="previewTable">{stories.slice(0,24).map((item:any)=><article key={item.story_key}><b>{item.story_key}</b><span>{item.title}</span><small>Sprint {item.sprint} · {item.assigned_to} · {item.priority} {item.jira_url&&<a href={item.jira_url} target="_blank" rel="noreferrer" style={{color:"#0052cc",fontWeight:700,marginLeft:"6px",textDecoration:"underline"}}>{item.jira_key||"Jira"} ↗</a>}</small></article>)}</div> {stories.length>24&&<p className="previewNote">Showing 24 of {stories.length}. Download Excel for the full plan, dashboard, and progress curve.</p>}</section>
 </div>;
}

function TestCasesPreview({document,jiraSync,onOpenJiraSync}:{document:any;jiraSync?:any;onOpenJiraSync?:()=>void}){
 const testCases=Array.isArray(document?.test_cases)?document.test_cases:[];
 const entryCriteria=Array.isArray(document?.entry_criteria)?document.entry_criteria:[];
 const exitCriteria=Array.isArray(document?.exit_criteria)?document.exit_criteria:[];
 return <div className="fsdPreview">
  {jiraSync&&<div className="jiraSyncBanner" style={{background:"#f0fdf4",border:"1px solid #bbf7d0",borderRadius:"10px",padding:"0.875rem 1.25rem",marginBottom:"1.25rem",display:"flex",justifyContent:"space-between",alignItems:"center"}}><div style={{display:"flex",alignItems:"center",gap:"0.75rem"}}><span style={{fontSize:"1.25rem"}}>🧪</span><div><strong style={{color:"#15803d",fontSize:"0.9375rem"}}>Jira Quality &amp; Tests Synchronized ({jiraSync.project_key})</strong><p style={{margin:0,fontSize:"0.8125rem",color:"#475569"}}>Synced {jiraSync.tests_synced||testCases.length} test verification cases {jiraSync.epic_key?`under Delivery Epic ${jiraSync.epic_key}`:""}</p></div></div>{jiraSync.board_url&&<a href={jiraSync.board_url} target="_blank" rel="noreferrer" style={{background:"#0052cc",color:"#fff",padding:"0.4rem 0.875rem",borderRadius:"6px",fontSize:"0.8125rem",fontWeight:600,textDecoration:"none"}}>Open Jira Board ↗</a>}</div>}
  <section>
   <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start"}}><p className="eyebrow">QUALITY &amp; TEST SUITE</p>{onOpenJiraSync&&<button type="button" onClick={onOpenJiraSync} style={{background:"#0052cc",color:"#ffffff",border:"none",borderRadius:"6px",padding:"0.45rem 0.9rem",fontSize:"0.8125rem",fontWeight:600,cursor:"pointer",display:"flex",alignItems:"center",gap:"0.4rem"}}><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M11.53 2c0 2.4 1.97 4.35 4.35 4.35h1.78v1.7c0 2.4 1.94 4.34 4.34 4.35V2h-10.47zM6.77 6.8c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V6.8H6.77zM2 11.6c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V11.6H2z"/></svg>Sync Tests to Jira</button>}</div>
   <h3>Grounded Quality Test Execution Pack</h3>
   <p>Every test case is directly linked to an approved requirement and verified against acceptance criteria and source evidence.</p>
   <div className="previewMetrics">
    <span><b>{testCases.length}</b> test cases</span>
    <span><b>{testCases.filter((t:any)=>String(t.priority).toLowerCase().includes("must")).length}</b> Must-Have tests</span>
    <span><b>{entryCriteria.length}</b> entry gates</span>
    <span><b>{exitCriteria.length}</b> exit criteria</span>
   </div>
  </section>

  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"1rem",marginBottom:"1.5rem"}}>
   {entryCriteria.length>0&&<section style={{background:"#f8fafc",border:"1px solid #e2e8f0",borderRadius:"8px",padding:"1rem"}}>
    <h4 style={{margin:"0 0 0.5rem 0",fontSize:"0.875rem",color:"#334155",textTransform:"uppercase",letterSpacing:"0.05em"}}>Entry Criteria</h4>
    <ul style={{margin:0,paddingLeft:"1.2rem",fontSize:"0.8125rem",color:"#475569",lineHeight:1.6}}>
     {entryCriteria.map((item:string,i:number)=><li key={i}>{item}</li>)}
    </ul>
   </section>}
   {exitCriteria.length>0&&<section style={{background:"#f8fafc",border:"1px solid #e2e8f0",borderRadius:"8px",padding:"1rem"}}>
    <h4 style={{margin:"0 0 0.5rem 0",fontSize:"0.875rem",color:"#334155",textTransform:"uppercase",letterSpacing:"0.05em"}}>Exit Criteria</h4>
    <ul style={{margin:0,paddingLeft:"1.2rem",fontSize:"0.8125rem",color:"#475569",lineHeight:1.6}}>
     {exitCriteria.map((item:string,i:number)=><li key={i}>{item}</li>)}
    </ul>
   </section>}
  </div>

  <section>
   <h3>Test Case Catalogue</h3>
   <div className="previewTable">
    {testCases.slice(0,25).map((item:any)=><article key={item.test_key}>
     <b>{item.test_key}</b>
     <span>{item.title}</span>
     <small>
      {item.requirement_key} · {item.priority} · {item.test_type||"Functional"}
      {item.jira_url&&<a href={item.jira_url} target="_blank" rel="noreferrer" style={{color:"#0052cc",fontWeight:700,marginLeft:"6px",textDecoration:"underline"}}>{item.jira_key||"Jira"} ↗</a>}
     </small>
    </article>)}
   </div>
   {testCases.length>25&&<p className="previewNote">Showing 25 of {testCases.length}. Download Excel or Jira CSV for the complete execution test pack.</p>}
  </section>
 </div>;
}

export default function ArtifactView({label,artifact,projectId,onGenerate,onGenerateStarterCode,onSuggestResources,onOpenJiraSync,starterCodeBusy=false,resourceBusy=false,generationBusy=false,processStatus,error}:{label:string;artifact?:Artifact;projectId?:string;onGenerate:()=>void;onGenerateStarterCode?:()=>void;onSuggestResources?:()=>void;onOpenJiraSync?:(mode?: "stories" | "tests")=>void;starterCodeBusy?:boolean;resourceBusy?:boolean;generationBusy?:boolean;processStatus?:ProcessingStatus|null;error?:string}){
 const [downloadError,setDownloadError]=useState("");
 const [downloading,setDownloading]=useState("");
 const document=artifact?.payload?.document;
 const timings:TimingRecord[]=processStatus?.timings||artifact?.payload?.timings||[];
 const generating=generationBusy||artifact?.status==="generating"||(processStatus?.status==="processing"&&!document);
 const backlog=artifact?.kind==="backlog";
 const testCases=artifact?.kind==="test_cases";
 const [elapsed,setElapsed]=useState(0);
 useEffect(()=>{if(!generating){setElapsed(0);return}const started=Date.now();const timer=window.setInterval(()=>setElapsed(Math.floor((Date.now()-started)/1000)),1000);return()=>window.clearInterval(timer)},[generating]);
 const downloads=artifact?.kind==="fsd"&&projectId?{docx:`/api/projects/${projectId}/artifacts/fsd/download/docx`,pdf:`/api/projects/${projectId}/artifacts/fsd/download/pdf`}:artifact?.kind==="backlog"&&projectId?{xlsx:`/api/projects/${projectId}/artifacts/backlog/download/xlsx`,resources_xlsx:`/api/projects/${projectId}/artifacts/backlog/resource-distribution/xlsx`,jira_csv:`/api/projects/${projectId}/artifacts/backlog/download/jira-csv`}:artifact?.kind==="technical_design"&&projectId?{docx:`/api/projects/${projectId}/artifacts/technical_design/download/docx`,pdf:`/api/projects/${projectId}/artifacts/technical_design/download/pdf`}:artifact?.kind==="test_cases"&&projectId?{xlsx:`/api/projects/${projectId}/artifacts/test_cases/download/xlsx`,jira_csv:`/api/projects/${projectId}/artifacts/test_cases/download/jira-csv`}:artifact?.payload?.downloads;
 const starterCode=artifact?.kind==="technical_design"?artifact?.payload?.starter_code:null;
 const resources=artifact?.kind==="backlog"?artifact?.payload?.resource_distribution:null;
 const jiraSync=artifact?.payload?.jira_sync||(artifact?.kind==="backlog"?artifact?.payload?.jira_sync:null);
 useEffect(()=>{if(!resources)return;window.document.getElementById("resource-distribution")?.scrollIntoView({block:"start",behavior:"smooth"})},[resources]);
 const downloadNote=artifact?.kind==="backlog"?"Download the official Project Planning Excel template or Jira-formatted CSV. Dashboard KPIs, health, duration, and the progress curve stay formula-driven.":artifact?.kind==="technical_design"?"Download the Technical Design as DOCX or PDF. Both include the InfraBeat header, application name, document control, technical flow, SAP design tables, test conditions, issues, and traceability.":artifact?.kind==="test_cases"?"Download the editable Quality Test Pack Excel or pre-formatted Jira/Xray CSV with execution tracking, status highlighting, coverage formulas, entry/exit criteria, and source evidence.":"Download the complete FSD with its process flowchart, screen navigation diagram, and generated screen wireframes.";
 async function downloadFile(path:string,format:string){
  try{
   setDownloadError("");setDownloading(format);
   const response=await fetch(`${API}${path}`);
   if(!response.ok){
    const body=await response.json().catch(()=>({detail:`Download failed with status ${response.status}`}));
    if(response.status===404)throw new Error("The download route is not active. Stop the old backend and restart it from apps/api.");
    throw new Error(body?.detail||`Download failed with status ${response.status}`);
   }
   const blob=await response.blob();
   const disposition=response.headers.get("content-disposition")||"";
   const encodedName=disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
   const plainName=disposition.match(/filename="?([^";]+)"?/i)?.[1];
   const filename=encodedName?decodeURIComponent(encodedName):plainName||`project-artifact.${format}`;
   const url=URL.createObjectURL(blob);const anchor=window.document.createElement("a");anchor.href=url;anchor.download=filename;
   window.document.body.appendChild(anchor);anchor.click();anchor.remove();URL.revokeObjectURL(url);
  }catch(problem){setDownloadError(problem instanceof Error?problem.message:"The file could not be downloaded")}finally{setDownloading("")}
 }
 return <><header><div><p className="eyebrow">{label.toUpperCase()}</p><h1>{label}.</h1></div><div className="live">{generating?"● Generating":document?"● Generated":"○ Ready to generate"}</div></header>
 {error&&<p className="error banner">{error}</p>}
 {downloadError&&<p className="error banner">{downloadError}</p>}
 {generating?<div className="fsdEmpty"><div className="analysisPanel" role="status">
  <div className="analysisHeading"><span className="spinner"/><div><b>{processStatus?.stage||(backlog?"Filling planning template":testCases?"Assembling test cases":"Preparing functional design")}</b><small>Elapsed {Math.floor(elapsed/60)}:{String(elapsed%60).padStart(2,"0")} · {backlog||testCases?"local template synthesis from approved requirements":"compact AI design followed by local baseline expansion"}</small></div><strong>{processStatus?.progress||5}%</strong></div>
  <div className="progressTrack"><span style={{width:`${processStatus?.progress||5}%`}}/></div>
   <div className="processConsole"><div className="consoleTitle"><span>{backlog?"PROJECT PLANNING":testCases?"QUALITY & TESTING":"LIVE FSD PROCESS"}</span><span>● {backlog||testCases?"no model call":"updating every 1.2s"}</span></div>{(processStatus?.logs||[]).map((log,i)=><div className={`consoleLine ${log.level}`} key={`${log.timestamp}-${i}`}><time>{new Date(log.timestamp).toLocaleTimeString()}</time><span>{log.message}</span></div>)}</div>
   <TimingPanel items={timings}/>
  <small className="keepOpen">{backlog?"Requirements are written into the Project Planning Excel template. Dashboard and progress-curve formulas are left unchanged.":testCases?"Test cases and criteria are derived directly from approved requirements and criteria.":"OpenAI generates only compact design decisions. The app adds all approved requirements, tests and traceability locally, then renders DOCX and PDF."}</small>
 </div></div>:
 !document?<div className="fsdEmpty"><h2>Generate from the approved baseline</h2><p>{backlog?"This fills the Project Planning Excel template from approved requirements. No model call is required. Suggest resources to see the team mix on this page, then download Resource Excel. Generate the plan to download Project Plan Excel or Sync to Jira.":testCases?"Generate the Quality & Testing pack from approved requirements with full traceability, criteria, and 1-click Jira test sync.":"This capability uses only approved, source-linked requirements. Review the generated result before using it for delivery."}</p><div className="emptyActions"><button disabled={generationBusy} onClick={onGenerate}>{generationBusy?"Generating…":artifact?.status==="failed"?"Retry":"Generate"} {label} →</button>{backlog&&onSuggestResources&&<button disabled={resourceBusy} onClick={onSuggestResources}>{resourceBusy?"Suggesting…":resources?"Regenerate Resource Distribution":"Suggest Project Resource Distribution"}</button>}{backlog&&downloads?.resources_xlsx&&<button type="button" className="downloadButton" disabled={!!downloading||resourceBusy} onClick={()=>downloadFile(downloads.resources_xlsx,"resources")}>{downloading==="resources"?"Preparing Excel…":"↓ Download Resource Excel"}</button>}</div><ResourcePreview distribution={resources} onDownload={downloads?.resources_xlsx?()=>downloadFile(downloads.resources_xlsx,"resources"):undefined} downloading={downloading==="resources"}/></div>:
  <div className="artifactDocument"><div className="artifactTitle"><div><p className="eyebrow">{String(document.status||"generated").replaceAll("_"," ")}</p><h2>{document.title}</h2></div><div className="artifactActions">{backlog&&onOpenJiraSync&&<button type="button" style={{background:"#0052cc",color:"#fff",borderColor:"#0052cc"}} onClick={()=>onOpenJiraSync("stories")}><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{marginRight:"5px"}}><path d="M11.53 2c0 2.4 1.97 4.35 4.35 4.35h1.78v1.7c0 2.4 1.94 4.34 4.34 4.35V2h-10.47zM6.77 6.8c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V6.8H6.77zM2 11.6c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V11.6H2z"/></svg>Sync to Jira</button>}{testCases&&onOpenJiraSync&&<button type="button" style={{background:"#0052cc",color:"#fff",borderColor:"#0052cc"}} onClick={()=>onOpenJiraSync("tests")}><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{marginRight:"5px"}}><path d="M11.53 2c0 2.4 1.97 4.35 4.35 4.35h1.78v1.7c0 2.4 1.94 4.34 4.34 4.35V2h-10.47zM6.77 6.8c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V6.8H6.77zM2 11.6c0 2.4 1.95 4.34 4.35 4.35h1.78v1.7c0 2.4 1.95 4.35 4.35 4.35V11.6H2z"/></svg>Sync Tests to Jira</button>}{artifact?.kind==="technical_design"&&onGenerateStarterCode&&<button disabled={starterCodeBusy||!!downloading} onClick={onGenerateStarterCode}>{starterCodeBusy?"Generating code…":starterCode?"Regenerate Starter Code":"Generate Starter Code"}</button>}{backlog&&onSuggestResources&&<button disabled={resourceBusy||!!downloading} onClick={onSuggestResources}>{resourceBusy?"Suggesting…":resources?"Regenerate Resource Distribution":"Suggest Project Resource Distribution"}</button>}{starterCode?.download&&<button className="downloadButton" disabled={!!downloading||starterCodeBusy} onClick={()=>downloadFile(starterCode.download,"zip")}>{downloading==="zip"?"Preparing ZIP…":"↓ Download Starter Code ZIP"}</button>}{downloads?.xlsx&&<button className="downloadButton" disabled={!!downloading} onClick={()=>downloadFile(downloads.xlsx,"xlsx")}>{downloading==="xlsx"?"Preparing Excel…":backlog?"↓ Download Project Plan Excel":testCases?"↓ Download Test Pack Excel":"↓ Download Excel"}</button>}{backlog&&downloads?.resources_xlsx&&<button className="downloadButton" disabled={!!downloading} onClick={()=>downloadFile(downloads.resources_xlsx,"resources")}>{downloading==="resources"?"Preparing Excel…":"↓ Download Resource Excel"}</button>}{downloads?.jira_csv&&<button className="downloadButton" disabled={!!downloading} onClick={()=>downloadFile(downloads.jira_csv,"csv")}>{downloading==="csv"?"Preparing CSV…":testCases?"↓ Download Jira Test CSV":"↓ Download Jira CSV"}</button>}{downloads?.docx&&<button className="downloadButton" disabled={!!downloading} onClick={()=>downloadFile(downloads.docx,"docx")}>{downloading==="docx"?"Preparing DOCX…":"↓ Download DOCX"}</button>}{downloads?.pdf&&<button className="downloadButton" disabled={!!downloading} onClick={()=>downloadFile(downloads.pdf,"pdf")}>{downloading==="pdf"?"Preparing PDF…":"↓ Download PDF"}</button>}<button onClick={onGenerate}>Regenerate</button></div></div>{downloadError&&<p className="error banner">{downloadError}</p>}{starterCode&&<p className="downloadNote">Starter package ready: {starterCode.file_count} files covering {starterCode.requirement_count} approved requirements, with Fiori, ABAP, tests, security guidance, and traceability.</p>}{downloads&&<p className="downloadNote">{downloadNote}</p>}<TimingPanel items={timings}/><FlowDiagrams document={document}/>{artifact?.kind==="fsd"?<FsdPreview document={document} validation={artifact?.payload?.validation}/>:backlog?<BacklogPreview document={document} resources={resources} jiraSync={jiraSync} onDownloadResources={downloads?.resources_xlsx?()=>downloadFile(downloads.resources_xlsx,"resources"):undefined} onOpenJiraSync={()=>onOpenJiraSync?.("stories")} downloading={downloading==="resources"}/>:testCases?<TestCasesPreview document={document} jiraSync={jiraSync} onOpenJiraSync={()=>onOpenJiraSync?.("tests")}/>:<div className="artifactBody">{Object.entries(document).filter(([k])=>!['title','status'].includes(k)).map(([k,v])=><Field key={k} name={k} value={v}/>)}</div>}</div>}</>
}
