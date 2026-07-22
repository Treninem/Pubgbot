const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let ME=null, CURRENT_CLAN_ID=null, OWNER_SECTION="overview", OWNER_USER_ID=null;
const initData=window.Telegram?.WebApp?.initData||"";
const headers={"Content-Type":"application/json"};
if(initData)headers["X-Telegram-Init-Data"]=initData;
else headers["X-Dev-Telegram-Id"]="100001";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const roleIcon=role=>({"Штурмовик":"19_assaulter_icon.webp","Снайпер":"20_sniper_icon.webp","Поддержка":"21_support_icon.webp","Разведчик":"39_premium_search_icon.webp","Универсал":"41_premium_trophy_icon.webp"}[role]||"39_premium_search_icon.webp");
const roleLabel=r=>({owner:"Владелец",officer:"Офицер",member:"Участник"}[r]||r||"");
const policyLabel=p=>({open:"Открытое вступление",approval:"Вступление по заявке",invite_only:"Только приглашения"}[p]||p||"");
const actionLabel=a=>({
  "clan.create":"Клан создан","clan.update":"Данные клана изменены","clan.join.open":"Игрок вступил",
  "clan.application.create":"Подана заявка","clan.application.accepted":"Заявка принята",
  "clan.application.rejected":"Заявка отклонена","clan.application.cancel":"Заявка отменена",
  "clan.invite.create":"Отправлено приглашение","clan.invite.accept":"Приглашение принято",
  "clan.invite.reject":"Приглашение отклонено","clan.member.role":"Изменена роль",
  "clan.member.kick":"Игрок исключён","clan.member.leave":"Игрок вышел","clan.owner.transfer":"Передан владелец",
  "clan.recruitment.open":"Набор открыт","clan.recruitment.close":"Набор закрыт","clan.disband":"Клан распущен"
}[a]||a);
async function api(path,opt={}){
  const r=await fetch("/api"+path,{...opt,headers:{...headers,...(opt.headers||{})}});
  if(!r.ok){
    const data=await r.json().catch(()=>({detail:r.statusText}));
    const detail=Array.isArray(data.detail)?data.detail.map(x=>x.msg||String(x)).join("; "):data.detail;
    throw new Error(detail||`Ошибка ${r.status}`);
  }
  return r.status===204?null:r.json();
}
function show(view){
  if(view==="owner"&&!ME?.is_owner){view="home";status("Раздел недоступен")}
  $$(".view").forEach(x=>x.classList.remove("active"));
  $$(".tabs [data-view]").forEach(x=>x.classList.remove("active"));
  $("#view-"+view)?.classList.add("active");
  $(`[data-view="${view}"]`)?.classList.add("active");
  scrollTo(0,0);loadView(view);
}
$$('[data-view]').forEach(b=>b.onclick=()=>show(b.dataset.view));
$$('[data-go]').forEach(b=>b.onclick=()=>show(b.dataset.go));
$("#backBtn").onclick=()=>show("home");
function status(t){$("#status").textContent=t;clearTimeout(status.timer);status.timer=setTimeout(()=>{$("#status").textContent=""},6000)}
function formJSON(form){
  const o=Object.fromEntries(new FormData(form));
  form.querySelectorAll('input[type=checkbox]').forEach(x=>o[x.name]=x.checked);
  form.querySelectorAll('input[type=number]').forEach(x=>o[x.name]=Number(x.value));
  return o;
}
function safeRun(fn){return async(...args)=>{try{return await fn(...args)}catch(e){status(e.message)}}}
async function boot(){
  try{
    ME=await api("/me");
    if(ME.is_owner){$("#ownerTab").hidden=false;$("#view-owner").hidden=false;}
    await stats();await loadProfile();
  }catch(e){status(e.message)}
}
async function stats(){
  const s=await api("/stats");
  $("#sUsers").textContent=s.users;$("#sProfiles").textContent=s.profiles;
  $("#sRooms").textContent=s.active_rooms;$("#sClans").textContent=s.clans;
}
async function loadView(v){
  try{
    if(v==="profiles")await loadProfiles();
    if(v==="rooms")await loadRooms();
    if(v==="clans")await loadClans();
    if(v==="invitations")await loadInvites();
    if(v==="ads")await loadAds();
    if(v==="owner")await loadOwner();
  }catch(e){status(e.message)}
}

// Profiles
$("#searchProfiles").onclick=safeRun(loadProfiles);
async function loadProfiles(){
  const p=new URLSearchParams();
  if($("#fServer").value)p.set("server",$("#fServer").value);
  if($("#fRole").value)p.set("role",$("#fRole").value);
  if($("#fRank").value)p.set("rank",$("#fRank").value);
  if($("#fMic").checked)p.set("has_mic","true");
  const rows=await api("/profiles?"+p);
  $("#profilesList").innerHTML=rows.length?rows.map(x=>`<article class="card media-card"><img class="card-icon" src="/static/assets/${roleIcon(x.role)}" width="88" height="88" alt=""><div class="card-content"><h3>${esc(x.nickname)}</h3><div class="tags"><span class="tag">${esc(x.server)}</span><span class="tag">${esc(x.rank||"Ранг не указан")}</span><span class="tag">${esc(x.role)}</span>${x.has_mic?'<span class="tag">🎤 Микрофон</span>':""}</div><p>${esc(x.about||"")}</p><div class="actions"><button data-invite="${x.user_id}">Пригласить</button><button data-fav-profile="${x.id}" aria-label="В избранное">☆</button><button data-report-profile="${x.id}">Пожаловаться</button></div></div></article>`).join(""):"<p class=muted>Подходящих анкет пока нет.</p>";
  $$('[data-invite]').forEach(b=>b.onclick=safeRun(()=>invite(Number(b.dataset.invite))));
  $$('[data-fav-profile]').forEach(b=>b.onclick=safeRun(()=>api(`/favorites/profile/${b.dataset.favProfile}`,{method:"POST"}).then(()=>status("Избранное обновлено"))));
  $$('[data-report-profile]').forEach(b=>b.onclick=()=>report("profile",Number(b.dataset.reportProfile)));
}
async function invite(id){await api("/invitations",{method:"POST",body:JSON.stringify({recipient_id:id,kind:"teammate",message:"Приглашение сыграть вместе"})});status("Приглашение отправлено")}

// Rooms
$("#showRoomForm").onclick=()=>$("#roomForm").classList.toggle("hidden");
$("#roomForm").onsubmit=safeRun(async e=>{e.preventDefault();await api("/rooms",{method:"POST",body:JSON.stringify(formJSON(e.target))});e.target.reset();$("#roomForm").classList.add("hidden");await loadRooms();await stats();status("Комната создана")});
async function loadRooms(){
  const rows=await api("/rooms");
  $("#roomsList").innerHTML=rows.length?rows.map(x=>`<article class="card media-card"><img class="card-icon" src="/static/assets/51_room_icon.webp" width="88" height="88" alt=""><div class="card-content"><h3>${esc(x.title)}</h3><div class="tags"><span class="tag">${esc(x.server)}</span><span class="tag">${esc(x.mode)}</span><span class="tag">👥 ${x.members_count}/${x.slots_total}</span>${x.mic_required?'<span class="tag">🎤 Микрофон</span>':""}</div><p>${esc(x.note||"")}</p><div class="actions"><button data-join-room="${x.id}">Вступить</button><button data-fav-room="${x.id}" aria-label="В избранное">☆</button><button data-report-room="${x.id}">Пожаловаться</button></div></div></article>`).join(""):"<p class=muted>Активных комнат нет.</p>";
  $$('[data-join-room]').forEach(b=>b.onclick=safeRun(async()=>{const x=await api(`/rooms/${b.dataset.joinRoom}/join`,{method:"POST"});status("Статус: "+x.status);await loadRooms()}));
  $$('[data-fav-room]').forEach(b=>b.onclick=safeRun(()=>api(`/favorites/room/${b.dataset.favRoom}`,{method:"POST"})));
  $$('[data-report-room]').forEach(b=>b.onclick=()=>report("room",Number(b.dataset.reportRoom)));
}

// Clans
$("#showClanForm").onclick=()=>$("#clanForm").classList.toggle("hidden");
$("#cancelClanForm").onclick=()=>$("#clanForm").classList.add("hidden");
$("#clanForm").onsubmit=safeRun(async e=>{
  e.preventDefault();
  const clan=await api("/clans",{method:"POST",body:JSON.stringify(formJSON(e.target))});
  e.target.reset();e.target.querySelector('[name="recruitment_open"]').checked=true;
  e.target.querySelector('[name="max_members"]').value=30;e.target.querySelector('[name="language"]').value="Русский";
  e.target.querySelector('[name="modes"]').value="Классика";$("#clanForm").classList.add("hidden");
  await loadClans();await stats();status("Клан создан");await openClan(clan.id);
});
$("#clanFilters").onsubmit=safeRun(async e=>{e.preventDefault();await loadClans()});
$("#resetClanFilters").onclick=safeRun(async()=>{$("#clanFilters").reset();await loadClans()});
$("#closeClanModal").onclick=closeClanModal;
$("#clanModal").onclick=e=>{if(e.target.id==="clanModal")closeClanModal()};
function closeClanModal(){$("#clanModal").classList.add("hidden");CURRENT_CLAN_ID=null}
function clanLogo(x){const src=x.logo_url?esc(x.logo_url):"/static/assets/40_premium_clan_icon.webp";return `<img class="clan-logo" src="${src}" alt="" onerror="this.src='/static/assets/40_premium_clan_icon.webp'">`}
function clanCard(x,mine=false){
  const joined=!!x.my_role;
  const applyText=x.join_policy==="open"?"Вступить":x.join_policy==="approval"?"Подать заявку":"Только по приглашению";
  const canApply=!joined&&x.recruitment_open&&!x.is_full&&x.join_policy!=="invite_only"&&x.my_application!=="pending";
  return `<article class="card clan-card ${mine?'my-clan-card':''}">
    <div class="clan-card-top">${clanLogo(x)}<div><small class="rank-place">#${x.rating_position||'—'} рейтинга</small><h3>${esc(x.name)} <span class="clan-tag">[${esc(x.tag)}]</span></h3><p class="muted compact">${esc(x.description||"Описание пока не добавлено")}</p></div></div>
    <div class="tags"><span class="tag">🌍 ${esc(x.server)}</span><span class="tag">🗣 ${esc(x.language)}</span><span class="tag">🎮 ${esc(x.modes||"Классика")}</span><span class="tag">🏆 ${esc(x.min_rank||"Без ограничения")}</span>${x.mic_required?'<span class="tag">🎤 Микрофон</span>':""}<span class="tag">👥 ${x.members_count}/${x.max_members}</span><span class="tag">⭐ ${x.rating_score}</span><span class="tag ${x.recruitment_open?'good':'bad'}">${x.recruitment_open?'Набор открыт':'Набор закрыт'}</span></div>
    <div class="actions"><button data-clan-open="${x.id}">${joined?"Открыть кабинет":"Подробнее"}</button>${canApply?`<button class="primary" data-clan-apply="${x.id}">${applyText}</button>`:""}${x.my_application==="pending"?'<span class="tag warn">Заявка на рассмотрении</span>':""}<button data-report-clan="${x.id}">Пожаловаться</button></div>
  </article>`;
}
async function loadClans(){
  const p=new URLSearchParams();
  if($("#cfQuery").value.trim())p.set("q",$("#cfQuery").value.trim());
  if($("#cfServer").value)p.set("server",$("#cfServer").value);
  if($("#cfLanguage").value.trim())p.set("language",$("#cfLanguage").value.trim());
  if($("#cfMode").value)p.set("mode",$("#cfMode").value);
  if($("#cfMap").value.trim())p.set("map_name",$("#cfMap").value.trim());
  if($("#cfRank").value.trim())p.set("min_rank",$("#cfRank").value.trim());
  if($("#cfPolicy").value)p.set("join_policy",$("#cfPolicy").value);
  if($("#cfMic").checked)p.set("mic_required","true");
  if($("#cfRecruitment").checked)p.set("recruitment_open","true");
  const [rows,mine]=await Promise.all([api("/clans?"+p),api("/clans/mine")]);
  $("#myClanBlock").classList.toggle("hidden",!mine);
  $("#myClanCard").innerHTML=mine?clanCard({...mine,rating_position:mine.rating_position||"—"},true):"";
  $("#showClanForm").disabled=!!mine;
  $("#showClanForm").title=mine?"Сначала выйдите из текущего клана":"";
  $("#clansList").innerHTML=rows.length?rows.map(x=>clanCard(x)).join(""):"<p class=muted>По выбранным фильтрам кланы не найдены.</p>";
  bindClanCards();
}
function bindClanCards(){
  $$('[data-clan-open]').forEach(b=>b.onclick=safeRun(()=>openClan(Number(b.dataset.clanOpen))));
  $$('[data-clan-apply]').forEach(b=>b.onclick=safeRun(()=>applyClan(Number(b.dataset.clanApply))));
  $$('[data-report-clan]').forEach(b=>b.onclick=()=>report("clan",Number(b.dataset.reportClan)));
}
async function applyClan(id){
  const message=prompt("Сообщение владельцу клана (необязательно)")||"";
  const x=await api(`/clans/${id}/apply`,{method:"POST",body:JSON.stringify({message})});
  status(x.status==="accepted"?"Вы вступили в клан":"Заявка отправлена");
  await loadClans();await openClan(id);
}
async function openClan(id){
  const x=await api(`/clans/${id}`);CURRENT_CLAN_ID=id;
  const joined=!!x.my_role;
  const applicationActions=x.applications?.map(a=>`<article class="subcard"><b>${esc(a.nickname)}</b><span class="muted"> ${esc(a.rank||"")} ${a.has_mic?'· 🎤':''}</span><p>${esc(a.message||"Без сообщения")}</p><div class="actions"><button class="primary" data-app-accept="${a.id}">Принять</button><button data-app-reject="${a.id}">Отклонить</button></div></article>`).join("")||'<p class="muted">Новых заявок нет.</p>';
  const members=x.members.map(m=>`<article class="member-row"><div><b>${esc(m.nickname)}</b><small>${esc(m.pubg_id?`ID ${m.pubg_id}`:m.display_name)} ${m.rank?`· ${esc(m.rank)}`:""}</small></div><span class="tag">${roleLabel(m.role)}</span><div class="actions member-actions">${x.is_owner&&m.role!=="owner"?`<button data-member-role="${m.user_id}" data-next-role="${m.role==='officer'?'member':'officer'}">${m.role==='officer'?'Снять офицера':'Назначить офицером'}</button><button data-member-transfer="${m.user_id}">Передать клан</button>`:""}${x.can_manage&&m.role!=="owner"?`<button data-member-kick="${m.user_id}" data-member-name="${esc(m.nickname)}">Исключить</button>`:""}</div></article>`).join("");
  const joinAction=!joined&&x.recruitment_open&&!x.is_full&&x.join_policy!=="invite_only"?`<button class="primary" id="modalClanApply">${x.join_policy==='open'?'Вступить':'Подать заявку'}</button>`:"";
  const leaveAction=joined&&x.my_role!=="owner"?'<button id="modalClanLeave">Выйти из клана</button>':"";
  const manager=`<section class="manager-panel"><h3>Управление кланом</h3><div class="actions"><button id="toggleRecruitment">${x.recruitment_open?'Закрыть набор':'Открыть набор'}</button><button id="inviteClanPlayer">Пригласить игрока</button><button id="showClanActivity">История действий</button></div><h4>Заявки</h4><div class="stack">${applicationActions}</div>${x.is_owner?'<div class="danger-zone"><h4>Владелец</h4><button id="disbandClan">Распустить клан</button></div>':""}</section>`;
  $("#clanModalContent").innerHTML=`
    <div class="clan-detail-head">${clanLogo(x)}<div><small id="clanModalTitle">КЛАН PUBG MOBILE</small><h2>${esc(x.name)} <span class="clan-tag">[${esc(x.tag)}]</span></h2><p>${esc(x.description||"Описание пока не добавлено")}</p></div></div>
    <div class="tags"><span class="tag">🌍 ${esc(x.server)}</span><span class="tag">🗣 ${esc(x.language)}</span><span class="tag">🎮 ${esc(x.modes)}</span><span class="tag">🗺 ${esc(x.maps||"Любые карты")}</span><span class="tag">🏆 ${esc(x.min_rank||"Без ограничения")}</span>${x.mic_required?'<span class="tag">🎤 Микрофон</span>':""}<span class="tag">👥 ${x.members_count}/${x.max_members}</span><span class="tag">⭐ ${x.rating_score}</span></div>
    <div class="detail-grid"><article><small>Тип вступления</small><b>${policyLabel(x.join_policy)}</b></article><article><small>Набор</small><b>${x.recruitment_open?'Открыт':'Закрыт'}</b></article><article><small>Контакт</small><b>${esc(x.contact||'Не указан')}</b></article><article><small>Ваша роль</small><b>${joined?roleLabel(x.my_role):'Не участник'}</b></article></div>
    <section><h3>Требования</h3><p>${esc(x.requirements||"Особых требований нет.")}</p></section>
    <div class="actions">${joinAction}${leaveAction}<button id="modalClanReport">Пожаловаться</button></div>
    <section><h3>Состав ${x.members_count}/${x.max_members}</h3><div class="members-list">${members}</div></section>
    ${x.can_manage?manager:""}`;
  $("#clanModal").classList.remove("hidden");
  bindClanModal(x);
}
function bindClanModal(x){
  $("#modalClanApply")?.addEventListener("click",safeRun(()=>applyClan(x.id)));
  $("#modalClanReport")?.addEventListener("click",()=>report("clan",x.id));
  $("#modalClanLeave")?.addEventListener("click",safeRun(async()=>{if(!confirm("Выйти из клана?"))return;await api(`/clans/${x.id}/leave`,{method:"POST"});closeClanModal();await loadClans();status("Вы вышли из клана")}));
  $("#toggleRecruitment")?.addEventListener("click",safeRun(async()=>{await api(`/clans/${x.id}/recruitment`,{method:"POST",body:JSON.stringify({recruitment_open:!x.recruitment_open})});await openClan(x.id);await loadClans();status("Статус набора изменён")}));
  $("#inviteClanPlayer")?.addEventListener("click",safeRun(async()=>{const recipient=prompt("Введите PUBG ID, ник, @username или внутренний ID игрока");if(!recipient)return;const message=prompt("Сообщение игроку (необязательно)")||"";await api(`/clans/${x.id}/invites`,{method:"POST",body:JSON.stringify({recipient,message})});status("Приглашение в клан отправлено")}));
  $$('[data-app-accept]').forEach(b=>b.onclick=safeRun(async()=>{await api(`/clans/${x.id}/applications/${b.dataset.appAccept}/decision`,{method:"POST",body:JSON.stringify({decision:"accept",note:""})});await openClan(x.id);await loadClans();status("Игрок принят")}));
  $$('[data-app-reject]').forEach(b=>b.onclick=safeRun(async()=>{const note=prompt("Причина отказа")||"";await api(`/clans/${x.id}/applications/${b.dataset.appReject}/decision`,{method:"POST",body:JSON.stringify({decision:"reject",note})});await openClan(x.id);status("Заявка отклонена")}));
  $$('[data-member-role]').forEach(b=>b.onclick=safeRun(async()=>{await api(`/clans/${x.id}/members/${b.dataset.memberRole}/role`,{method:"POST",body:JSON.stringify({role:b.dataset.nextRole})});await openClan(x.id);status("Роль изменена")}));
  $$('[data-member-kick]').forEach(b=>b.onclick=safeRun(async()=>{if(!confirm(`Исключить ${b.dataset.memberName}?`))return;await api(`/clans/${x.id}/members/${b.dataset.memberKick}`,{method:"DELETE"});await openClan(x.id);await loadClans();status("Игрок исключён")}));
  $$('[data-member-transfer]').forEach(b=>b.onclick=safeRun(async()=>{if(!confirm("Передать этому участнику права владельца?"))return;await api(`/clans/${x.id}/transfer`,{method:"POST",body:JSON.stringify({user_id:Number(b.dataset.memberTransfer)})});await openClan(x.id);await loadClans();status("Клан передан новому владельцу")}));
  $("#showClanActivity")?.addEventListener("click",safeRun(async()=>{const rows=await api(`/clans/${x.id}/activity`);const html=rows.length?rows.map(r=>`<article class="subcard"><b>${esc(actionLabel(r.action))}</b><small>${esc(r.actor)} · ${new Date(r.created_at).toLocaleString()}</small></article>`).join(""):'<p class="muted">История пока пуста.</p>';$("#clanModalContent").insertAdjacentHTML("beforeend",`<section id="activityBlock"><h3>История действий</h3><div class="stack">${html}</div></section>`);$("#activityBlock").scrollIntoView({behavior:"smooth"})}));
  $("#disbandClan")?.addEventListener("click",safeRun(async()=>{if(!confirm("Распустить клан без возможности восстановления?"))return;await api(`/clans/${x.id}/disband`,{method:"POST"});closeClanModal();await loadClans();await stats();status("Клан распущен")}));
}

// Invitations
async function loadInvites(){
  const [rows,clanRows]=await Promise.all([api("/invitations"),api("/clans/invites/mine")]);
  $("#clanInvitationsList").innerHTML=clanRows.length?clanRows.map(x=>`<article class="card"><h3>${esc(x.clan_name)} <span class="clan-tag">[${esc(x.clan_tag)}]</span></h3><p>${esc(x.message||`Приглашение от ${x.invited_by}`)}</p><div class="tags"><span class="tag">${esc(x.status)}</span></div>${x.status==="pending"?`<div class="actions"><button class="primary" data-clan-inv-accept="${x.id}">Принять</button><button data-clan-inv-reject="${x.id}">Отклонить</button><button data-clan-open="${x.clan_id}">Клан</button></div>`:""}</article>`).join(""):"<p class=muted>Приглашений в кланы нет.</p>";
  $("#invitationsList").innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>${esc(x.kind)}</h3><p>${esc(x.message)}</p><div class="tags"><span class="tag">${esc(x.status)}</span></div>${x.recipient_id===ME.id&&x.status==="pending"?`<div class="actions"><button data-inv-accept="${x.id}">Принять</button><button data-inv-reject="${x.id}">Отклонить</button></div>`:""}</article>`).join(""):"<p class=muted>Игровых приглашений нет.</p>";
  $$('[data-clan-inv-accept]').forEach(b=>b.onclick=safeRun(async()=>{const r=await api(`/clans/invites/${b.dataset.clanInvAccept}/decision`,{method:"POST",body:JSON.stringify({decision:"accept"})});status("Вы вступили в клан");await loadInvites();await stats();if(r.clan_id)await openClan(r.clan_id)}));
  $$('[data-clan-inv-reject]').forEach(b=>b.onclick=safeRun(async()=>{await api(`/clans/invites/${b.dataset.clanInvReject}/decision`,{method:"POST",body:JSON.stringify({decision:"reject"})});await loadInvites();status("Приглашение отклонено")}));
  $$('[data-inv-accept]').forEach(b=>b.onclick=safeRun(()=>decideInvite(b.dataset.invAccept,"accept")));
  $$('[data-inv-reject]').forEach(b=>b.onclick=safeRun(()=>decideInvite(b.dataset.invReject,"reject")));
  $$('[data-clan-open]').forEach(b=>b.onclick=safeRun(()=>openClan(Number(b.dataset.clanOpen))));
}
async function decideInvite(id,d){await api(`/invitations/${id}/${d}`,{method:"POST"});await loadInvites()}

// Profile
async function loadProfile(){const x=await api("/profiles/mine");if(!x)return;Object.entries(x).forEach(([k,v])=>{const e=$(`#profileForm [name="${k}"]`);if(e){if(e.type==="checkbox")e.checked=!!v;else e.value=v??""}})}
$("#profileForm").onsubmit=safeRun(async e=>{e.preventDefault();await api("/profiles/mine",{method:"PUT",body:JSON.stringify(formJSON(e.target))});status("Анкета сохранена");await stats()});

// Ads and reports
const adStatusLabel=s=>({draft:"Черновик",awaiting_payment:"Ожидает оплату",pending_moderation:"На модерации",active:"Активно",rejected:"Отклонено",expired:"Завершено",refunded:"Возвращено"}[s]||s||"—");
async function loadTariffs(){
  const rows=await api("/ads/tariffs");
  $("#adTariff").innerHTML=rows.length?rows.map(x=>`<option value="${x.id}">${esc(x.name)} — ${x.price_stars} ⭐ / ${x.duration_days} дн.</option>`).join(""):`<option value="">Нет доступных тарифов</option>`;
  $("#adTariffCards").innerHTML=rows.map(x=>`<article class="card tariff-card ${x.is_pinned?'tariff-top':''}"><h3>${esc(x.name)}</h3><b>${x.price_stars} ⭐</b><p>${esc(x.description||'')}</p><div class="tags"><span class="tag">${x.duration_days} дней</span><span class="tag">${esc(x.placement)}</span>${x.is_pinned?'<span class="tag good">Закрепление</span>':''}</div></article>`).join("");
}
$("#adForm").onsubmit=safeRun(async e=>{
  e.preventDefault();const payload=formJSON(e.target);payload.tariff_id=Number(payload.tariff_id);
  const x=await api("/ads",{method:"POST",body:JSON.stringify(payload)});
  status(`Заявка создана. К оплате: ${x.price_stars} Stars.`);e.target.reset();await loadAds();
});
async function payAd(adId){
  const invoice=await api(`/ads/${adId}/invoice`,{method:"POST"});
  if(invoice.dev_mode){
    if(confirm(`Тестовый режим. Имитировать оплату ${invoice.amount} Stars?`))await api(`/ads/payments/${invoice.payment_id}/simulate`,{method:"POST"});
    await loadAds();return;
  }
  if(!invoice.invoice_link)throw new Error("Ссылка на счёт не получена");
  if(window.Telegram?.WebApp?.openInvoice){
    window.Telegram.WebApp.openInvoice(invoice.invoice_link,async()=>{await loadAds()});
  }else window.open(invoice.invoice_link,"_blank","noopener");
}
async function openAd(adId){const x=await api(`/ads/${adId}/click`,{method:"POST"});if(window.Telegram?.WebApp?.openTelegramLink)window.Telegram.WebApp.openTelegramLink(x.url);else window.open(x.url,"_blank","noopener")}
async function loadAds(){
  await loadTariffs();
  const [mine,rows]=await Promise.all([api("/ads/mine"),api("/ads")]);
  $("#myAdsList").innerHTML=mine.length?mine.map(x=>`<article class="card ${x.is_pinned?'ad-pinned':''}"><h3>#${x.id} ${esc(x.title)}</h3><p>${esc(x.text)}</p><div class="tags"><span class="tag">${esc(adStatusLabel(x.status))}</span><span class="tag">${x.price_stars} ⭐</span><span class="tag">${x.duration_days} дней</span><span class="tag">Показы: ${x.impressions}</span><span class="tag">Переходы: ${x.clicks}</span></div>${x.rejection_reason?`<p class="status">${esc(x.rejection_reason)}</p>`:''}<div class="actions">${['draft','awaiting_payment'].includes(x.status)?`<button class="primary" data-ad-pay="${x.id}">Оплатить ${x.price_stars} ⭐</button>`:''}</div></article>`).join(""):"<p class=muted>У вас пока нет рекламных заявок.</p>";
  $("#adsList").innerHTML=rows.length?rows.map(x=>`<article class="card media-card ${x.is_pinned?'ad-pinned':''}"><img class="card-icon" src="/static/assets/42_premium_ads_icon.webp" width="88" height="88" alt=""><div class="card-content"><h3>${x.is_pinned?'📌 ':''}${esc(x.title)}</h3><p>${esc(x.text)}</p><div class="tags"><span class="tag">${esc(x.category)}</span><span class="tag">${esc(x.placement)}</span></div><button data-ad-open="${x.id}">Открыть</button></div></article>`).join(""):"<p class=muted>Активной рекламы нет.</p>";
  $$('[data-ad-pay]').forEach(b=>b.onclick=safeRun(()=>payAd(Number(b.dataset.adPay))));
  $$('[data-ad-open]').forEach(b=>b.onclick=safeRun(()=>openAd(Number(b.dataset.adOpen))));
  rows.forEach(x=>api(`/ads/${x.id}/impression`,{method:"POST"}).catch(()=>{}));
}
async function report(kind,id){try{const category=prompt("Категория жалобы: спам, оскорбления, мошенничество, читы, опасная ссылка");if(!category)return;const text=prompt("Опишите нарушение");if(!text)return;await api("/reports",{method:"POST",body:JSON.stringify({target_kind:kind,target_id:id,category,text})});status("Жалоба отправлена")}catch(e){status(e.message)}}

// Owner panel
const OWNER_METRIC_LABELS={users:"Пользователи",new_users_7d:"Новые за 7 дней",banned:"Заблокированы",muted:"С мутом",ads_blocked:"Запрет рекламы",rooms:"Комнаты",rooms_open:"Открытые комнаты",rooms_blocked:"Заблокированные комнаты",clans:"Кланы",clans_active:"Активные кланы",clans_blocked:"Заблокированные кланы",ads_pending:"Реклама на проверке",payments_paid:"Оплаченные счета",stars_received:"Получено Stars",stars_refunded:"Возвращено Stars",reports_open:"Открытые жалобы",broadcasts:"Рассылки"};
const systemRoleLabel=r=>({owner:"Владелец",admin:"Администратор",moderator:"Модератор",user:"Игрок"}[r]||r||"—");
const fmtDate=v=>{if(!v)return"—";const d=new Date(v);return Number.isNaN(d.getTime())?esc(v):d.toLocaleString()};
const ownerPanelId=name=>name==="overview"?"owner-overview":`owner-${name}-panel`;
function showOwnerSection(name){OWNER_SECTION=name;$$('.owner-panel').forEach(x=>x.classList.remove('active'));$$('[data-owner-section]').forEach(x=>x.classList.toggle('active',x.dataset.ownerSection===name));$(`#${ownerPanelId(name)}`)?.classList.add('active')}
async function loadOwner(){
  if(!ME?.is_owner)return;
  await loadOwnerDashboard();showOwnerSection(OWNER_SECTION);await loadOwnerSection(OWNER_SECTION);
}
async function loadOwnerSection(name){
  if(name==="overview")return loadOwnerStatistics();
  if(name==="users")return loadOwnerUsers();
  if(name==="rooms")return loadOwnerRooms();
  if(name==="clans")return loadOwnerClans();
  if(name==="ads"){await loadOwnerAds();await loadOwnerPayments();return loadOwnerTariffs()}
  if(name==="reports")return loadOwnerReports();
  if(name==="broadcasts")return loadOwnerBroadcasts();
  if(name==="audit")return loadOwnerAudit();
  if(name==="system")return loadOwnerSystem();
}
async function loadOwnerDashboard(){
  const d=await api('/owner/dashboard');
  const keys=['users','new_users_7d','banned','muted','ads_blocked','rooms_open','rooms_blocked','clans_active','clans_blocked','ads_pending','payments_paid','stars_received','stars_refunded','reports_open','broadcasts'];
  $('#ownerMetrics').innerHTML=keys.map(k=>`<article><span>${esc(OWNER_METRIC_LABELS[k]||k)}</span><b>${d[k]??0}</b></article>`).join('');
}
async function loadOwnerStatistics(){
  const data=await api(`/owner/statistics?days=${Number($('#ownerStatsDays').value||30)}`);
  const roleText=Object.entries(data.roles).map(([k,v])=>`${systemRoleLabel(k)}: ${v}`).join(' · ')||'Нет данных';
  const summary=[['Роли',roleText],['Комнаты',Object.entries(data.rooms_by_status).map(([k,v])=>`${k}: ${v}`).join(' · ')],['Кланы',Object.entries(data.clans_by_status).map(([k,v])=>`${k}: ${v}`).join(' · ')],['Реклама',Object.entries(data.ads_by_status).filter(([,v])=>v).map(([k,v])=>`${k}: ${v}`).join(' · ')||'Нет объявлений']];
  $('#ownerStatusSummary').innerHTML=summary.map(([a,b])=>`<article><b>${esc(a)}</b><p>${esc(b)}</p></article>`).join('');
  $('#ownerTimeline').innerHTML=data.timeline.slice().reverse().map(x=>`<tr><td>${esc(x.date)}</td><td>${x.users}</td><td>${x.rooms}</td><td>${x.clans}</td><td>${x.ads}</td><td>${x.reports}</td></tr>`).join('');
  $('#ownerTopClans').innerHTML=data.top_clans.length?data.top_clans.map(x=>`<article class="card"><h3>${esc(x.name)} <span class="clan-tag">[${esc(x.tag)}]</span></h3><div class="tags"><span class="tag">Участников: ${x.members_count}</span><span class="tag">Очки: ${x.rating_points}</span></div><button data-clan-open="${x.id}">Открыть</button></article>`).join(''):'<p class="muted">Активных кланов пока нет.</p>';
  $$('[data-clan-open]').forEach(b=>b.onclick=safeRun(()=>openClan(Number(b.dataset.clanOpen))));
}
async function loadOwnerUsers(){
  const p=new URLSearchParams();if($('#ownerUserQuery').value)p.set('query',$('#ownerUserQuery').value);if($('#ownerUserRole').value)p.set('role',$('#ownerUserRole').value);if($('#ownerUserStatus').value)p.set('status',$('#ownerUserStatus').value);p.set('limit','100');
  const data=await api('/owner/users?'+p);$('#ownerUsersMeta').textContent=`Найдено: ${data.total}`;
  $('#ownerUsers').innerHTML=data.items.length?data.items.map(x=>{const online=x.last_seen_at&&Date.now()-new Date(x.last_seen_at).getTime()<10*60*1000;return `<article class="card admin-user-card"><div class="admin-card-head"><div><h3>${esc(x.nickname||x.display_name)} <small>#${x.id}</small></h3><p class="muted">Telegram: ${x.telegram_id}${x.username?` · @${esc(x.username)}`:''}${x.pubg_id?` · PUBG ID ${esc(x.pubg_id)}`:''}</p></div><span class="tag ${online?'good':''}">${online?'Онлайн':'Был '+fmtDate(x.last_seen_at)}</span></div><div class="tags"><span class="tag">${esc(systemRoleLabel(x.role))}</span>${x.server?`<span class="tag">${esc(x.server)}</span>`:''}${x.rank?`<span class="tag">${esc(x.rank)}</span>`:''}${x.clan?`<span class="tag">[${esc(x.clan.tag)}] ${esc(x.clan.name)}</span>`:''}${x.is_banned?'<span class="tag bad">Бан</span>':''}${x.is_muted?'<span class="tag warn">Мут</span>':''}${x.ads_blocked?'<span class="tag bad">Реклама запрещена</span>':''}</div><div class="actions"><button data-owner-user="${x.id}">Открыть профиль</button></div></article>`}).join(''):'<p class="muted">Пользователи не найдены.</p>';
  $$('[data-owner-user]').forEach(b=>b.onclick=safeRun(()=>openOwnerUser(Number(b.dataset.ownerUser))));
}
function closeOwnerModal(){$('#ownerModal').classList.add('hidden');OWNER_USER_ID=null}
async function openOwnerUser(id){
  OWNER_USER_ID=id;const data=await api(`/owner/users/${id}`),u=data.user,p=data.profile,editable=['owner','admin'].includes(ME.role),staff=ME.role!=='moderator';
  const profileForm=p?`<h3>Игровая анкета</h3><div class="form-grid"><input name="nickname" value="${esc(p.nickname)}" placeholder="Ник"><input name="pubg_id" value="${esc(p.pubg_id)}" placeholder="PUBG ID"><input name="server" value="${esc(p.server)}" placeholder="Сервер"><input name="language" value="${esc(p.language)}" placeholder="Язык"><input name="rank" value="${esc(p.rank)}" placeholder="Ранг"><input name="player_role" value="${esc(p.role)}" placeholder="Игровая роль"><input name="modes" value="${esc(p.modes)}" placeholder="Режимы"><input name="maps" value="${esc(p.maps)}" placeholder="Карты"><input name="play_time" value="${esc(p.play_time)}" placeholder="Время игры"><input name="timezone" value="${esc(p.timezone)}" placeholder="Часовой пояс"><input name="play_style" value="${esc(p.play_style)}" placeholder="Стиль"><input name="goal" value="${esc(p.goal)}" placeholder="Цель"></div><textarea name="about" placeholder="О себе">${esc(p.about)}</textarea><label><input type="checkbox" name="has_mic" ${p.has_mic?'checked':''}> Есть микрофон</label><label><input type="checkbox" name="is_visible" ${p.is_visible?'checked':''}> Анкета видна</label><label><input type="checkbox" name="looking_for_team" ${p.looking_for_team?'checked':''}> Ищет команду</label>`:'<p class="muted">Игровая анкета ещё не создана.</p>';
  const editBlock=editable?`<form id="ownerUserEditForm" class="panel"><h3>Редактирование</h3><div class="form-grid"><input name="display_name" value="${esc(u.display_name)}" placeholder="Имя"><input name="username" value="${esc(u.username||'')}" placeholder="Username"></div><textarea name="moderation_note" placeholder="Внутренняя заметка">${esc(u.moderation_note||'')}</textarea>${profileForm}<button type="submit">Сохранить изменения</button></form>`:'';
  const roleBlock=ME.role==='owner'&&u.role!=='owner'?`<div class="actions"><select id="ownerNewRole"><option value="user" ${u.role==='user'?'selected':''}>Игрок</option><option value="moderator" ${u.role==='moderator'?'selected':''}>Модератор</option><option value="admin" ${u.role==='admin'?'selected':''}>Администратор</option></select><button data-user-action="set_role">Изменить роль</button></div>`:'';
  const actionBlock=u.role==='owner'?'<p class="muted">Учётная запись владельца защищена.</p>':`<div class="danger-zone"><h3>Доступ и ограничения</h3><div class="actions">${staff?`<button data-user-action="${u.is_banned?'unban':'ban'}">${u.is_banned?'Разблокировать':'Заблокировать'}</button>`:''}<button data-user-action="${u.is_muted?'unmute':'mute'}">${u.is_muted?'Снять мут':'Выдать мут'}</button>${staff?`<button data-user-action="${u.ads_blocked?'unblock_ads':'block_ads'}">${u.ads_blocked?'Разрешить рекламу':'Запретить рекламу'}</button>`:''}</div>${roleBlock}</div>`;
  const clanBlock=data.clan?`<article class="subcard"><b>${esc(data.clan.clan.name)} [${esc(data.clan.clan.tag)}]</b><small>Роль: ${esc(roleLabel(data.clan.membership.role))}</small><button data-clan-open="${data.clan.clan.id}">Открыть клан</button></article>`:'<p class="muted">Не состоит в активном клане.</p>';
  $('#ownerModalContent').innerHTML=`<h2 id="ownerModalTitle">${esc(p?.nickname||u.display_name)} <small>#${u.id}</small></h2><div class="tags"><span class="tag">${esc(systemRoleLabel(u.role))}</span>${u.is_banned?'<span class="tag bad">Заблокирован</span>':''}${u.is_muted?`<span class="tag warn">Мут до ${fmtDate(u.mute_until)}</span>`:''}${u.ads_blocked?'<span class="tag bad">Реклама запрещена</span>':''}</div><div class="detail-grid"><article><small>Telegram ID</small><b>${u.telegram_id}</b></article><article><small>Username</small><b>${u.username?'@'+esc(u.username):'—'}</b></article><article><small>Регистрация</small><b>${fmtDate(u.created_at)}</b></article><article><small>Последняя активность</small><b>${fmtDate(u.last_seen_at)}</b></article></div>${editBlock}${actionBlock}<section><h3>Клан</h3>${clanBlock}</section><section><h3>Созданные комнаты (${data.rooms.length})</h3><div class="stack">${data.rooms.slice(0,10).map(x=>`<article class="subcard"><b>#${x.id} ${esc(x.title)}</b><small>${esc(x.status)} · ${esc(x.server)} · ${esc(x.mode)}</small></article>`).join('')||'<p class="muted">Нет комнат.</p>'}</div></section><section><h3>Реклама (${data.ads.length})</h3><div class="stack">${data.ads.slice(0,10).map(x=>`<article class="subcard"><b>#${x.id} ${esc(x.title)}</b><small>${esc(x.status)} · ${x.price_stars} Stars</small></article>`).join('')||'<p class="muted">Нет рекламы.</p>'}</div></section><section><h3>Жалобы (${data.reports.length})</h3><div class="stack">${data.reports.map(x=>`<article class="subcard"><b>${esc(x.category)}</b><p>${esc(x.text)}</p><small>${esc(x.status)} · ${fmtDate(x.created_at)}</small></article>`).join('')||'<p class="muted">Жалоб нет.</p>'}</div></section><section><h3>История модерации</h3><div class="stack">${data.audit.map(x=>`<article class="subcard"><b>${esc(x.action)}</b><small>${fmtDate(x.created_at)} · ${esc(x.details||'')}</small></article>`).join('')||'<p class="muted">История пуста.</p>'}</div></section>`;
  $('#ownerModal').classList.remove('hidden');
  $('#ownerUserEditForm')?.addEventListener('submit',safeRun(async e=>{e.preventDefault();await api(`/owner/users/${id}`,{method:'PATCH',body:JSON.stringify(formJSON(e.target))});status('Профиль обновлён');await openOwnerUser(id);await loadOwnerUsers()}));
  $$('[data-user-action]').forEach(b=>b.onclick=safeRun(()=>ownerUserAction(id,b.dataset.userAction)));
  $$('[data-clan-open]').forEach(b=>b.onclick=safeRun(()=>openClan(Number(b.dataset.clanOpen))));
}
async function ownerUserAction(id,action){
  let reason='',duration_hours=null,role=null;
  if(['ban','mute','block_ads'].includes(action)){reason=prompt('Причина ограничения')||'';if(!reason)return}
  if(action==='mute'){duration_hours=Number(prompt('Срок мута в часах','24')||24);if(!Number.isFinite(duration_hours)||duration_hours<1)return status('Неверный срок мута')}
  if(action==='set_role'){role=$('#ownerNewRole').value;if(!confirm(`Назначить роль «${systemRoleLabel(role)}»?`))return}
  await api(`/owner/users/${id}/actions`,{method:'POST',body:JSON.stringify({action,reason,duration_hours,role})});status('Доступ пользователя изменён');await openOwnerUser(id);await loadOwnerUsers();await loadOwnerDashboard();
}
async function loadOwnerRooms(){
  const p=new URLSearchParams();if($('#ownerRoomQuery').value)p.set('query',$('#ownerRoomQuery').value);if($('#ownerRoomStatus').value)p.set('status',$('#ownerRoomStatus').value);
  const rows=await api('/owner/rooms?'+p);$('#ownerRooms').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>#${x.id} ${esc(x.title)}</h3><p class="muted">Владелец: ${esc(x.owner.display_name)}${x.owner.username?` (@${esc(x.owner.username)})`:''}</p><div class="tags"><span class="tag">${esc(x.status)}</span><span class="tag">${esc(x.server)}</span><span class="tag">${esc(x.mode)}</span><span class="tag">${x.members_count}/${x.slots_total}</span></div>${x.moderation_reason?`<p>${esc(x.moderation_reason)}</p>`:''}<div class="actions">${['closed','blocked'].includes(x.status)?`<button data-owner-room="${x.id}" data-decision="reopen">Открыть снова</button>`:`<button data-owner-room="${x.id}" data-decision="close">Закрыть</button>`}<button data-owner-room="${x.id}" data-decision="block">Заблокировать</button><button data-owner-user="${x.owner.id}">Владелец</button></div></article>`).join(''):'<p class="muted">Комнаты не найдены.</p>';
  $$('[data-owner-room]').forEach(b=>b.onclick=safeRun(async()=>{const decision=b.dataset.decision,reason=decision==='reopen'?'':(prompt('Причина решения')||'');if(decision!=='reopen'&&!reason)return;await api(`/owner/rooms/${b.dataset.ownerRoom}`,{method:'POST',body:JSON.stringify({decision,reason})});await loadOwnerRooms();await loadOwnerDashboard();status('Статус комнаты изменён')}));
  $$('[data-owner-user]').forEach(b=>b.onclick=safeRun(()=>openOwnerUser(Number(b.dataset.ownerUser))));
}
async function loadOwnerClans(){
  const p=new URLSearchParams();if($('#ownerClanQuery').value)p.set('query',$('#ownerClanQuery').value);if($('#ownerClanStatus').value)p.set('status',$('#ownerClanStatus').value);
  const rows=await api('/owner/clans?'+p);$('#ownerClans').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>#${x.id} ${esc(x.name)} [${esc(x.tag)}]</h3><div class="tags"><span class="tag">${esc(x.status)}</span><span class="tag">${x.members_count}/${x.max_members}</span><span class="tag">Жалоб: ${x.open_reports}</span></div>${x.blocked_reason?`<p>${esc(x.blocked_reason)}</p>`:''}<div class="actions">${x.status==='active'?`<button data-clan-open="${x.id}">Открыть</button><button data-owner-clan="${x.id}" data-decision="block">Заблокировать</button>`:`${x.status==='blocked'?`<button data-owner-clan="${x.id}" data-decision="unblock">Разблокировать</button>`:''}`}<button data-owner-clan="${x.id}" data-decision="close">Закрыть</button><button data-owner-user="${x.owner_id}">Владелец</button></div></article>`).join(''):'<p class="muted">Кланы не найдены.</p>';
  $$('[data-owner-clan]').forEach(b=>b.onclick=safeRun(async()=>{const decision=b.dataset.decision,reason=decision==='unblock'?'':(prompt('Причина решения')||'');if(decision!=='unblock'&&!reason)return;await api(`/owner/clans/${b.dataset.ownerClan}`,{method:'POST',body:JSON.stringify({decision,reason})});await loadOwnerClans();await loadOwnerDashboard();status('Статус клана изменён')}));
  $$('[data-clan-open]').forEach(b=>b.onclick=safeRun(()=>openClan(Number(b.dataset.clanOpen))));$$('[data-owner-user]').forEach(b=>b.onclick=safeRun(()=>openOwnerUser(Number(b.dataset.ownerUser))));
}
async function loadOwnerAds(){
  const p=new URLSearchParams();if($('#ownerAdStatus').value)p.set('status',$('#ownerAdStatus').value);const rows=await api('/owner/ads?'+p);
  $('#ownerAds').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>#${x.id} ${esc(x.title)}</h3><p>${esc(x.text)}</p><p class="muted">${esc(x.owner.display_name)} · ${x.price_stars} Stars · ${esc(x.status)}</p><div class="actions"><button data-owner-user="${x.owner.id}">Автор</button>${x.status==='pending_moderation'?`<button data-ad-approve="${x.id}">Одобрить</button><button data-ad-reject="${x.id}">Отклонить</button>`:''}</div></article>`).join(''):'<p class="muted">Объявления не найдены.</p>';
  $$('[data-ad-approve]').forEach(b=>b.onclick=safeRun(()=>moderateAd(b.dataset.adApprove,'approve')));$$('[data-ad-reject]').forEach(b=>b.onclick=safeRun(()=>moderateAd(b.dataset.adReject,'reject')));$$('[data-owner-user]').forEach(b=>b.onclick=safeRun(()=>openOwnerUser(Number(b.dataset.ownerUser))));
}
async function moderateAd(id,decision){const reason=decision==='reject'?(prompt('Причина отказа')||''):'';if(decision==='reject'&&!reason)return;await api(`/owner/ads/${id}`,{method:'POST',body:JSON.stringify({decision,reason})});await loadOwnerAds();await loadOwnerDashboard();status('Реклама обработана')}
async function loadOwnerPayments(){
  const p=new URLSearchParams();if($('#ownerPaymentStatus').value)p.set('status',$('#ownerPaymentStatus').value);
  const rows=await api('/owner/payments?'+p);
  $('#ownerPayments').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>Платёж #${x.id} · ${x.amount} ⭐</h3><p class="muted">${esc(x.user.display_name)} · Telegram ${x.user.telegram_id} · объявление #${x.ad.id} ${esc(x.ad.title)}</p><div class="tags"><span class="tag">${esc(x.status)}</span><span class="tag">${esc(x.currency)}</span><span class="tag">${fmtDate(x.paid_at||x.created_at)}</span>${x.tariff?`<span class="tag">${esc(x.tariff.name)}</span>`:''}</div>${x.refund_reason?`<p>Возврат: ${esc(x.refund_reason)}</p>`:''}<div class="actions"><button data-owner-user="${x.user.id}">Пользователь</button>${x.status==='paid'?`<button data-payment-refund="${x.id}">Вернуть ${x.amount} ⭐</button>`:''}</div></article>`).join(''):'<p class="muted">Платежи не найдены.</p>';
  $$('[data-payment-refund]').forEach(b=>b.onclick=safeRun(async()=>{const reason=prompt('Причина возврата Stars');if(!reason)return;if(!confirm('Выполнить реальный возврат Telegram Stars?'))return;await api(`/owner/payments/${b.dataset.paymentRefund}/refund`,{method:'POST',body:JSON.stringify({reason})});await loadOwnerPayments();await loadOwnerAds();await loadOwnerDashboard();status('Stars возвращены')}));
  $$('[data-owner-user]').forEach(b=>b.onclick=safeRun(()=>openOwnerUser(Number(b.dataset.ownerUser))));
}
function resetOwnerTariffForm(){const f=$('#ownerTariffForm');f.reset();f.elements.id.value='';f.elements.priority.value=0;f.elements.is_active.checked=true}
async function loadOwnerTariffs(){
  const rows=await api('/owner/tariffs');
  $('#ownerTariffs').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>#${x.id} ${esc(x.name)} · ${x.price_stars} ⭐</h3><p>${esc(x.description||'')}</p><div class="tags"><span class="tag">${x.duration_days} дней</span><span class="tag">${esc(x.placement)}</span><span class="tag">Приоритет ${x.priority}</span>${x.is_pinned?'<span class="tag good">Закрепление</span>':''}<span class="tag ${x.is_active?'good':'bad'}">${x.is_active?'Активен':'Выключен'}</span></div><button data-tariff-edit="${x.id}">Редактировать</button></article>`).join(''):'<p class="muted">Тарифов нет.</p>';
  $$('[data-tariff-edit]').forEach(b=>b.onclick=()=>{const x=rows.find(v=>v.id===Number(b.dataset.tariffEdit));if(!x)return;const f=$('#ownerTariffForm');Object.entries(x).forEach(([k,v])=>{const e=f.elements[k];if(!e)return;if(e.type==='checkbox')e.checked=!!v;else e.value=v??''});f.scrollIntoView({behavior:'smooth'});});
}
async function loadOwnerReports(){
  const p=new URLSearchParams();if($('#ownerReportStatus').value)p.set('status',$('#ownerReportStatus').value);const rows=await api('/owner/reports?'+p);
  $('#ownerReports').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>#${x.id} ${esc(x.category)}</h3><p>${esc(x.text)}</p><div class="tags"><span class="tag">${esc(x.target_kind)} #${x.target_id}</span><span class="tag">${esc(x.status)}</span><span class="tag">${fmtDate(x.created_at)}</span></div>${x.resolution?`<p class="muted">Решение: ${esc(x.resolution)}</p>`:''}${x.status==='open'?`<button data-report-close="${x.id}">Закрыть жалобу</button>`:''}</article>`).join(''):'<p class="muted">Жалобы не найдены.</p>';
  $$('[data-report-close]').forEach(b=>b.onclick=safeRun(async()=>{const reason=prompt('Решение по жалобе','Проверено владельцем')||'';if(!reason)return;await api(`/owner/reports/${b.dataset.reportClose}`,{method:'POST',body:JSON.stringify({decision:'close',reason})});await loadOwnerReports();await loadOwnerDashboard();status('Жалоба закрыта')}));
}
async function loadOwnerBroadcasts(){const rows=await api('/owner/broadcasts');$('#ownerBroadcasts').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>${esc(x.title)}</h3><p>${esc(x.text)}</p><div class="tags"><span class="tag">${esc(x.target)}</span><span class="tag">Получателей: ${x.recipients_count}</span><span class="tag">${fmtDate(x.created_at)}</span></div></article>`).join(''):'<p class="muted">Рассылок ещё не было.</p>'}
async function loadOwnerSystem(){
  const x=await api('/owner/system/status'),r=x.runtime||{};
  const items=[
    ['Версия',x.version],['Окружение',x.environment],['База',x.database_backend],
    ['Telegram',x.telegram_mode],['Домен',x.public_base_url||'Не задан'],
    ['База доступна',r.database_ready?'Да':'Нет'],['Бот',r.bot_ready?'Запущен':'Отключён'],
    ['Webhook',r.webhook_ready?'Готов':'Не готов'],['Последняя копия',fmtDate(r.last_backup_at)],
    ['Ошибка webhook',r.last_webhook_error||'Нет'],['Ошибка копирования',r.last_backup_error||'Нет']
  ];
  $('#ownerSystemStatus').innerHTML=items.map(([a,b])=>`<article><span>${esc(a)}</span><b>${esc(String(b??'—'))}</b></article>`).join('');
}
async function loadOwnerAudit(){
  const p=new URLSearchParams();if($('#ownerAuditAction').value)p.set('action',$('#ownerAuditAction').value);if($('#ownerAuditKind').value)p.set('object_kind',$('#ownerAuditKind').value);if($('#ownerAuditActor').value)p.set('actor_id',$('#ownerAuditActor').value);const rows=await api('/owner/audit?'+p);
  $('#ownerAudit').innerHTML=rows.length?rows.map(x=>`<article class="card"><h3>${esc(x.action)}</h3><p class="muted">${x.actor?`${esc(x.actor.display_name)} #${x.actor.id}`:'Система'} · ${esc(x.object_kind||'—')} ${x.object_id??''} · ${fmtDate(x.created_at)}</p>${x.details?`<pre class="audit-details">${esc(x.details)}</pre>`:''}</article>`).join(''):'<p class="muted">Записи не найдены.</p>';
}
$$('[data-owner-section]').forEach(b=>b.onclick=safeRun(async()=>{showOwnerSection(b.dataset.ownerSection);await loadOwnerSection(OWNER_SECTION)}));
$('#ownerRefresh').onclick=safeRun(loadOwner);$('#ownerStatsRefresh').onclick=safeRun(loadOwnerStatistics);
$('#ownerUserFilters').onsubmit=safeRun(async e=>{e.preventDefault();await loadOwnerUsers()});$('#ownerUserReset').onclick=safeRun(async()=>{$('#ownerUserFilters').reset();await loadOwnerUsers()});
$('#ownerRoomFilters').onsubmit=safeRun(async e=>{e.preventDefault();await loadOwnerRooms()});$('#ownerClanFilters').onsubmit=safeRun(async e=>{e.preventDefault();await loadOwnerClans()});
$('#ownerSystemRefresh').onclick=safeRun(loadOwnerSystem);$('#ownerCreateBackup').onclick=safeRun(async()=>{if(!confirm('Создать резервную копию базы сейчас?'))return;const r=await api('/owner/system/backup',{method:'POST'});status(`Резервная копия создана: ${r.file}`);await loadOwnerSystem()});
$('#ownerAdsRefresh').onclick=safeRun(loadOwnerAds);$('#ownerPaymentsRefresh').onclick=safeRun(loadOwnerPayments);$('#ownerReportsRefresh').onclick=safeRun(loadOwnerReports);$('#ownerAuditFilters').onsubmit=safeRun(async e=>{e.preventDefault();await loadOwnerAudit()});
$('#ownerTariffReset').onclick=resetOwnerTariffForm;
$('#ownerTariffForm').onsubmit=safeRun(async e=>{e.preventDefault();const payload=formJSON(e.target),id=Number(payload.id||0);delete payload.id;const path=id?`/owner/tariffs/${id}`:'/owner/tariffs';await api(path,{method:id?'PATCH':'POST',body:JSON.stringify(payload)});resetOwnerTariffForm();await loadOwnerTariffs();await loadTariffs();status('Тариф сохранён')});
$('#broadcastForm').onsubmit=safeRun(async e=>{e.preventDefault();const payload=formJSON(e.target);if(!confirm('Отправить уведомление выбранной группе?'))return;const result=await api('/owner/broadcasts',{method:'POST',body:JSON.stringify(payload)});e.target.reset();status(`Рассылка отправлена: ${result.recipients_count} получателей`);await loadOwnerBroadcasts();await loadOwnerDashboard()});
$('#closeOwnerModal').onclick=closeOwnerModal;$('#ownerModal').onclick=e=>{if(e.target.id==='ownerModal')closeOwnerModal()};


window.Telegram?.WebApp?.ready();window.Telegram?.WebApp?.expand();window.Telegram?.WebApp?.BackButton?.onClick(()=>show("home"));boot();
