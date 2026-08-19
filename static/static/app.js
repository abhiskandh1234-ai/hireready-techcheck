const $=id=>document.getElementById(id);
let currentUser=null, readinessScore=null, lastAI=null;
const state={internet:null,camera:null,mic:null,browser:null,device:null,screen:null};

async function api(url,options={}){
  const res=await fetch(url,{headers:{"Content-Type":"application/json",...(options.headers||{})},...options});
  let data={};try{data=await res.json()}catch{}
  if(!res.ok)throw new Error(data.detail||"Request failed");
  return data;
}
function msg(el,text,error=false){el.textContent=text;el.classList.remove("hidden","error");if(error)el.classList.add("error")}
function toast(text,error=false){
  const el=$("toast");if(!el)return;
  el.textContent=text;el.classList.toggle("error",error);el.classList.add("show");
  clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>el.classList.remove("show"),2600);
}
function setLoading(button,loading,label){
  if(!button)return;button.disabled=loading;
  if(loading){button.dataset.label=button.innerHTML;button.textContent=label}
  else if(button.dataset.label){button.innerHTML=button.dataset.label;delete button.dataset.label}
}
async function bootstrap(){
  try{currentUser=await api("/api/me");showWorkspace()}catch{$("authView").classList.remove("hidden")}
}
async function showWorkspace(){
  $("authView").classList.add("hidden");$("landingPanel").classList.add("hidden");$("how-it-works").classList.add("hidden");$("userArea").classList.remove("hidden");
  $("userLabel").textContent=`${currentUser.name} · ${currentUser.role}`;
  $("candidateView").classList.toggle("hidden",currentUser.role!=="candidate");
  $("adminView").classList.toggle("hidden",currentUser.role!=="admin");
  await loadAIStatus();if(currentUser.role==="admin")loadAdmin();
}
async function loadAIStatus(){
  try{
    const s=await api("/api/ai/status");
    $("modelLabel").textContent=s.model?`Powered by ${s.model}`:"AI model";
    $("aiBadge").innerHTML=`<i></i>${s.configured?"AI connected":"AI unavailable"}`;
    $("aiBadge").classList.toggle("on",s.configured);$("aiBadge").classList.toggle("off",!s.configured);
  }catch{}
}

$("registerBtn").onclick=async()=>{
  const b=$("registerBtn");setLoading(b,true,"Creating account…");
  try{currentUser=await api("/api/register",{method:"POST",body:JSON.stringify({name:$("regName").value,email:$("regEmail").value,password:$("regPassword").value})});showWorkspace();toast("Account created. Welcome to HireReady.")}
  catch(e){msg($("authMessage"),e.message,true)}finally{setLoading(b,false)}
};
$("loginBtn").onclick=async()=>{
  const b=$("loginBtn");setLoading(b,true,"Signing in…");
  try{currentUser=await api("/api/login",{method:"POST",body:JSON.stringify({email:$("loginEmail").value,password:$("loginPassword").value})});showWorkspace();toast("Signed in successfully.")}
  catch(e){msg($("authMessage"),e.message,true)}finally{setLoading(b,false)}
};
$("logoutBtn").onclick=async()=>{await api("/api/logout",{method:"POST"});location.reload()};

function setCard(name,status,detail,level){
  state[name]=level==="ok";
  const c=$(`${name}Card`);c.classList.remove("ok","warn","fail");c.classList.add(level);
  const badge=c.querySelector(".check-state");if(badge)badge.textContent=level==="ok"?"Ready":level==="warn"?"Review":"Action needed";
  $(`${name}Status`).textContent=status;$(`${name}Detail`).textContent=detail;
}
function checkInternet(){
  if(!navigator.onLine){setCard("internet","Offline","Browser reports no active network connection.","fail");return}
  const c=navigator.connection||navigator.mozConnection||navigator.webkitConnection;
  if(c){const weak=["slow-2g","2g"].includes(c.effectiveType);setCard("internet",weak?"Connected, weak":"Connected",`${c.effectiveType||"network"}; ${c.downlink||"?"} Mbps estimated; ${c.rtt||"?"} ms RTT.`,weak?"warn":"ok")}
  else setCard("internet","Connected","Browser reports an active network connection.","ok")
}
async function checkMedia(){
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw new Error("Media API unavailable");
    const stream=await navigator.mediaDevices.getUserMedia({video:true,audio:true});
    const v=stream.getVideoTracks(),a=stream.getAudioTracks();
    v.length?setCard("camera","Camera ready",`Detected: ${v[0].label||"camera input"}.`,"ok"):setCard("camera","Not detected","No camera input was returned.","fail");
    a.length?setCard("mic","Microphone ready",`Detected: ${a[0].label||"microphone input"}.`,"ok"):setCard("mic","Not detected","No microphone input was returned.","fail");
    stream.getTracks().forEach(t=>t.stop());
  }catch{setCard("camera","Needs attention","Camera permission or device access failed.","fail");setCard("mic","Needs attention","Microphone permission or device access failed.","fail")}
}
function checkBrowser(){const secure=window.isSecureContext||location.hostname==="localhost";setCard("browser",secure?"Browser ready":"HTTPS recommended",navigator.userAgent.includes("Chrome")?"Chrome / Chromium detected in a secure context.":"Modern browser detected.",secure?"ok":"warn")}
function checkDevice(){setCard("device","Device detected",`${navigator.hardwareConcurrency||"?"} logical CPU cores; ${navigator.deviceMemory||"?"} GB reported memory.`,"ok")}
function checkScreen(){const good=screen.width>=1280&&screen.height>=720;setCard("screen",good?"Display ready":"Small display",`${screen.width} × ${screen.height} screen resolution.`,good?"ok":"warn")}
function updateScore(){
  const vals=Object.values(state);readinessScore=Math.round(vals.filter(Boolean).length/vals.length*100);
  $("score").textContent=`${readinessScore}%`;$("scoreRing").style.setProperty("--score",readinessScore);
  if(readinessScore===100){$("scoreText").textContent="Ready to join";$("recommendation").textContent="All baseline checks passed. Your interview setup looks healthy."}
  else if(readinessScore>=67){$("scoreText").textContent="Almost ready";$("recommendation").textContent="Most checks passed. Review the items marked for attention before joining."}
  else{$("scoreText").textContent="Needs attention";$("recommendation").textContent="Resolve the failed checks before joining your interview."}
}
$("runAllBtn").onclick=async()=>{
  const b=$("runAllBtn");setLoading(b,true,"Running diagnostics…");
  checkInternet();checkBrowser();checkDevice();checkScreen();await checkMedia();updateScore();
  setLoading(b,false);toast(`TechCheck complete — ${readinessScore}% readiness.`)
};
function systemReport(){return ["HireReady TechCheck Report",`Readiness: ${readinessScore===null?"Not checked":readinessScore+"%"}`,`Internet: ${$("internetStatus").textContent}`,`Camera: ${$("cameraStatus").textContent}`,`Microphone: ${$("micStatus").textContent}`,`Browser: ${$("browserStatus").textContent}`,`Device: ${$("deviceStatus").textContent}`,`Display: ${$("screenStatus").textContent}`].join("\n")}
$("copyReportBtn").onclick=async()=>{try{await navigator.clipboard.writeText(systemReport());toast("Diagnostic report copied to clipboard.")}catch{toast("Could not copy the report.",true)}};

$("askAiBtn").onclick=async()=>{
  const issue=$("aiIssue").value.trim();if(issue.length<5){msg($("aiMessage"),"Describe the problem in a little more detail.",true);return}
  const b=$("askAiBtn");setLoading(b,true,"AI is analyzing…");$("aiMessage").classList.add("hidden");
  try{
    lastAI=await api("/api/ai/troubleshoot",{method:"POST",body:JSON.stringify({issue,interview_minutes:Number($("aiInterviewMinutes").value),readiness_score:readinessScore,system_report:systemReport()})});
    $("aiCategory").textContent=lastAI.category;$("aiPriority").textContent=lastAI.priority;$("aiPriority").className=`priority-${lastAI.priority}`;
    $("aiCause").textContent=lastAI.likely_cause;$("aiEscalation").textContent=lastAI.escalation_reason;
    $("aiSteps").innerHTML="";lastAI.steps.forEach(s=>{const li=document.createElement("li");li.textContent=s;$("aiSteps").appendChild(li)});
    $("aiResult").classList.remove("hidden");$("aiResult").scrollIntoView({behavior:"smooth",block:"nearest"});toast("AI troubleshooting plan is ready.")
  }catch(e){msg($("aiMessage"),e.message,true)}finally{setLoading(b,false)}
};

$("aiTicketBtn").onclick=()=>{
  if(!lastAI)return;$("ticketPanel").classList.remove("hidden");$("ticketMinutes").value=$("aiInterviewMinutes").value;$("ticketCategory").value=lastAI.category;$("ticketDescription").value=$("aiIssue").value;$("ticketAiSummary").value=lastAI.summary;$("ticketPanel").scrollIntoView({behavior:"smooth",block:"start"})
};
$("submitTicketBtn").onclick=async()=>{
  const b=$("submitTicketBtn");setLoading(b,true,"Submitting ticket…");
  try{
    const d=await api("/api/tickets",{method:"POST",body:JSON.stringify({category:$("ticketCategory").value,description:$("ticketDescription").value,interview_minutes:Number($("ticketMinutes").value),readiness_score:readinessScore,system_report:systemReport(),ai_summary:$("ticketAiSummary").value||null,ai_priority:lastAI?.priority||null})});
    msg($("ticketMessage"),`Ticket ${d.ticket_code} created with ${d.priority} priority.`);toast(`Support ticket ${d.ticket_code} created.`)
  }catch(e){msg($("ticketMessage"),e.message,true)}finally{setLoading(b,false)}
};

$("myTicketsBtn").onclick=async()=>{
  try{
    const tickets=await api("/api/tickets");$("myTicketsPanel").classList.remove("hidden");$("myTicketsList").innerHTML="";
    if(!tickets.length){$("myTicketsList").innerHTML="<div class='ticket-item'><strong>No tickets yet</strong><small>Your submitted support tickets will appear here.</small></div>";return}
    tickets.forEach(t=>{const div=document.createElement("div");div.className="ticket-item";div.innerHTML=`<div><strong>${safe(t.ticket_code)}</strong> · ${safe(t.category)} · <span class="priority-${safe(t.priority)}">${safe(t.priority)}</span> · ${safe(t.status)}</div><small>${safe(t.description)}</small>${t.ai_summary?`<small><b>AI summary:</b> ${safe(t.ai_summary)}</small>`:""}`;$("myTicketsList").appendChild(div)});
    $("myTicketsPanel").scrollIntoView({behavior:"smooth",block:"start"});
  }catch(e){toast(e.message,true)}
};
function safe(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
function renderBars(el,data,labelKey){
  el.innerHTML="";if(!data.length){el.innerHTML="<p class='muted'>No data yet.</p>";return}
  const max=Math.max(...data.map(x=>x.count),1);data.forEach(x=>{const row=document.createElement("div");row.className="bar-row";row.innerHTML=`<span>${safe(x[labelKey])}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.round(x.count/max*100)}%"></div></div><span class="bar-value">${x.count}</span>`;el.appendChild(row)})
}
async function loadAdmin(){
  try{
    const s=await api("/api/admin/stats");$("statTotal").textContent=s.total;$("statOpen").textContent=s.open;$("statHigh").textContent=s.high;$("statResolved").textContent=s.resolved;$("statResolution").textContent=`${s.resolution_rate}%`;$("statReadiness").textContent=s.average_readiness===null?"—":`${s.average_readiness}%`;renderBars($("categoryBars"),s.categories,"category");renderBars($("priorityBars"),s.priorities,"priority");await loadAdminTickets();
  }catch(e){toast(e.message,true)}
}
async function loadAdminTickets(){
  const params=new URLSearchParams();if($("filterSearch").value.trim())params.set("search",$("filterSearch").value.trim());if($("filterStatus").value)params.set("status",$("filterStatus").value);if($("filterPriority").value)params.set("priority",$("filterPriority").value);
  const tickets=await api(`/api/tickets?${params.toString()}`);$("adminTicketBody").innerHTML="";
  if(!tickets.length){$("adminTicketBody").innerHTML='<tr><td colspan="6">No matching tickets.</td></tr>';return}
  tickets.forEach(t=>{const tr=document.createElement("tr");tr.innerHTML=`<td><strong>${safe(t.ticket_code)}</strong></td><td><strong>${safe(t.candidate_name)}</strong><br><small>${safe(t.candidate_email)}</small></td><td><strong>${safe(t.category)}</strong><br><small>${safe(t.description.slice(0,70))}</small>${t.ai_summary?`<br><small><b>AI:</b> ${safe(t.ai_summary.slice(0,90))}</small>`:""}</td><td class="priority-${safe(t.priority)}">${safe(t.priority)}</td><td>${safe(t.status)}</td><td>${t.status==="Open"?`<button class="resolve" data-code="${safe(t.ticket_code)}">Resolve</button>`:"—"}</td>`;$("adminTicketBody").appendChild(tr)});
  document.querySelectorAll(".resolve").forEach(b=>b.onclick=async()=>{b.disabled=true;await api(`/api/tickets/${b.dataset.code}/resolve`,{method:"POST"});toast(`Ticket ${b.dataset.code} resolved.`);await loadAdmin()})
}
$("refreshAdminBtn").onclick=()=>{loadAdmin();toast("Dashboard refreshed.")};$("applyFiltersBtn").onclick=loadAdminTickets;$("filterSearch").addEventListener("keydown",e=>{if(e.key==="Enter")loadAdminTickets()});$("exportBtn").onclick=()=>{window.location.href="/api/admin/export.csv"};
bootstrap();
