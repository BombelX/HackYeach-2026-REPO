const icons = {
  shield:'<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z"/><path d="m8 12 3 3 5-6"/>',
  camera:'<path d="M8 6 10 3h4l2 3h4a2 2 0 0 1 2 2v11H2V8a2 2 0 0 1 2-2h4Z"/><circle cx="12" cy="12" r="4"/>',
  arrow:'<path d="M4 12h15m-6-6 6 6-6 6"/>',
  back:'<path d="M20 12H5m6-6-6 6 6 6"/>',
  chevron:'<path d="m6 9 6 6 6-6"/>',
  eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
  phone:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 5h4m-3 14h2"/>',
  document:'<path d="M14 2H5v20h14V7l-5-5Z"/><path d="M14 2v5h5M8 12h8m-8 4h6"/>',
  warning:'<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  transfer:'<path d="M3 7h17m-5-4 5 4-5 4M21 17H4m5-4-5 4 5 4"/>',
  home:'<path d="m3 10 9-8 9 8v12H3V10Z"/><path d="M9 22v-8h6v8"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  right:'<path d="m9 5 7 7-7 7"/>'
};
const icon = (name, size = 20) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.shield}</svg>`;
const routes = [{id:'login',name:'Logowanie'},{id:'sms',name:'Kod SMS'},{id:'dashboard',name:'Pulpit'},{id:'transfer',name:'Przelew'},{id:'warning',name:'Ostrzeżenie'}];
const state = {remember:false,stream:null,transfer:{beneficiary:'',account:'',amount:'',title:''},warningAnswer:null,result:null,scenario:'standard',balance:18420.50,history:[],historyQuery:'',lastTransfer:null,returnRoute:'login',operationId:1,closedOperations:new Map(),credentials:{login:'',password:''},cameraRequest:0,cameraPending:false};
const invoice = {beneficiary:'Pracownia Forma',account:'12 3456 7890 1234 5678 9012 3456',amount:'1250,00',title:'Faktura FV/10/2026'};
const screen = document.querySelector('#screen');
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const money = value => Number(String(value).replace(/\s/g,'').replace(',','.')).toLocaleString('pl-PL',{minimumFractionDigits:2,maximumFractionDigits:2})+' zł';
const bankNav = current => `<nav class="bank-nav" aria-label="Nawigacja konta"><button data-route="dashboard" class="${current==='dashboard'?'active':''}" ${current==='dashboard'?'aria-current="page"':''}>Moje konto</button><button data-route="transfer" class="${current==='transfer'?'active':''}" ${current==='transfer'?'aria-current="page"':''}>Przelewy</button><button data-route="history" class="${current==='history'?'active':''}" ${current==='history'?'aria-current="page"':''}>Historia</button></nav>`;
const button = (text,action,kind='primary',extra='') => `<button class="${kind}-button" data-action="${action}" ${extra}>${text}</button>`;
let toastTimeout;
function toast(message){clearTimeout(toastTimeout);const el=document.querySelector('#toast');el.textContent=message;el.hidden=false;toastTimeout=setTimeout(()=>el.hidden=true,7000);}
function navigate(route){if(location.hash===`#${route}`)render(route);else location.hash=route;}
function field(name,label,placeholder,extra=''){return `<label class="field"><span>${label}</span><input name="${name}" id="${name}" placeholder="${placeholder}" value="${escapeHTML(state.transfer[name]||'')}" ${extra}></label>`;}
function progress(current,labels=['Dane przelewu','Podsumowanie','Potwierdzenie']){return `<ol class="steps" aria-label="Etapy ${labels.length===2?'logowania':'przelewu'}">${labels.map((label,index)=>`<li class="${index+1===current?'current':index+1<current?'complete':''}" ${index+1===current?'aria-current="step"':''}><span class="step-number" aria-hidden="true">${index+1<current?icon('check',16):index+1}</span><span>${label}</span></li>`).join('')}</ol>`;}
function render(route,focus=true){
  if(!['login','sms','dashboard','transfer','review','warning','confirm','result','history','help'].includes(route))route='login';
  if(['review','warning','confirm'].includes(route)&&restoreClosedOperation()){history.replaceState(null,'','#result');route='result';}
  document.querySelector('#prototype-menu').open=false;
  if(['review','warning','confirm'].includes(route)&&Object.values(state.transfer).every(value=>!value.trim()))state.transfer={...invoice};
  const auth=route==='login'||route==='sms'||(route==='help'&&['login','sms'].includes(state.returnRoute));
  document.querySelector('#brand-home').href=auth?'#login':'#dashboard';
  document.querySelector('#brand-home').setAttribute('aria-label',auth?'Bank24, ekran logowania':'Bank24, moje konto');
  document.querySelector('#layout').className=`layout ${auth?'auth-layout':'bank-layout'}`;
  document.querySelector('#logout').hidden=auth;
  document.querySelector('#session-guidance').hidden=!['login','sms'].includes(route);
  document.querySelector('#camera-title').textContent='Twoja kamera';
  document.querySelector('#prototype-nav').innerHTML=routes.map(r=>`<button class="prototype-tab" data-route="${r.id}" ${route===r.id || ((route==='review'||route==='confirm')&&r.id==='transfer') || (route==='result'&&r.id==='warning')?'aria-current="page"':''}>${r.name}</button>`).join('');
  const view={login:loginView,sms:smsView,dashboard:dashboardView,transfer:transferView,review:reviewView,warning:warningView,confirm:confirmView,result:resultView,history:historyView,help:helpView}[route]||loginView;
  screen.innerHTML=view();
  if(route==='warning'&&state.warningAnswer)setWarningAnswer(state.warningAnswer);
  screen.querySelectorAll('form').forEach(form=>form.addEventListener('submit',onSubmit));
  if(focus){screen.querySelector("h1")?.setAttribute("tabindex","-1");(screen.querySelector("h1")||screen).focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
  document.title=`${({login:'Logowanie',sms:'Kod SMS',dashboard:'Moje konto',transfer:'Przelew',review:'Podsumowanie',warning:'Zatrzymaj się na chwilę',confirm:'Potwierdzenie przelewu',result:'Wynik',history:'Historia operacji',help:'Pomoc'})[route]||'Logowanie'} · Bank24 · prototyp`;
}
function loginView(){return `<div class="auth-inner">${progress(1,['Logowanie','Kod SMS'])}<h1 id="screen-title">Zaloguj się do Bank24</h1><p class="screen-intro">Wpisz dane konta demonstracyjnego. W kolejnym kroku potwierdzisz logowanie kodem SMS.</p><form id="login-form" class="login-form" novalidate><label class="field"><span>Login</span><input id="login-input" name="login" type="text" autocomplete="off" placeholder="anna.demo" value="${escapeHTML(state.credentials.login)}" aria-describedby="form-error" required></label><label class="field"><span>Hasło</span><div class="password-control"><input id="password" name="password" type="password" autocomplete="off" placeholder="Hasło konta demo" value="${escapeHTML(state.credentials.password)}" aria-describedby="form-error" required><button type="button" data-action="password" aria-label="Pokaż hasło" aria-pressed="false">${icon('eye')}</button></div></label><label class="checkbox-row"><input id="remember" name="remember" type="checkbox" ${state.remember?'checked':''}>Zapamiętaj urządzenie</label><p class="remember-help">W tym podglądzie wybór obowiązuje tylko do wylogowania.</p><p id="form-error" class="inline-error" role="alert" hidden></p><button class="primary-button full-width" type="submit">Zaloguj się ${icon('arrow',19)}</button></form><div class="under-form"><button class="text-button" data-action="forgot">Nie pamiętam hasła</button><button class="text-button" data-action="help">Potrzebuję pomocy</button></div><div class="demo-note"><div class="demo-note-heading"><strong>Konto demonstracyjne</strong><button class="text-button" data-action="fill-demo">Uzupełnij dane demo</button></div>Login: <strong>anna.demo</strong> · hasło: <strong>bank24</strong><br>To fikcyjne konto. Używaj wyłącznie danych demonstracyjnych.</div></div>`;}
function smsView(){return `<div class="auth-inner"><button class="text-button back-button" data-route="login">${icon('back',17)} Wróć do logowania</button>${progress(2,['Logowanie','Kod SMS'])}<h1 id="screen-title">Potwierdź, że to Ty</h1><p class="screen-intro">Wpisz 4-cyfrowy kod SMS dla numeru<br><strong>+48 ••• ••• 482</strong>.</p><form id="sms-form" class="sms-form" novalidate><label class="field-label" for="sms-code">Kod SMS</label><input class="sms-input" id="sms-code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="4" pattern="[0-9]{4}" aria-describedby="sms-help form-error" required><span class="field-help" id="sms-help">W prototypie użyj kodu <strong>1234</strong>. SMS nie jest wysyłany.</span><p id="form-error" class="inline-error" role="alert" hidden></p><button class="primary-button full-width" type="submit">Potwierdź i przejdź do konta ${icon('arrow',19)}</button></form><button class="text-button" data-action="resend">Wyślij kod ponownie</button><div class="sms-note">${icon('shield',21)}<span>Nie podawaj kodu osobie, która do Ciebie dzwoni. Pracownik banku nie powinien prosić o kod logowania.</span></div>${state.remember?'<p class="field-help">Podgląd: po potwierdzeniu urządzenie zostanie oznaczone jako zapamiętane. Prototyp nie zapisuje tokenu.</p>':''}</div>`;}
function dashboardView(){
  const records=transactionRecords();const period=records.filter(t=>t.month===10);
  const incoming=period.filter(t=>t.incoming).reduce((sum,t)=>sum+t.amount,0);const outgoing=period.filter(t=>!t.incoming).reduce((sum,t)=>sum+t.amount,0);
  return `${bankNav('dashboard')}<div class="greeting"><div><h1 id="screen-title">Dzień dobry, Anno</h1><p>Twoje finanse w jednym miejscu.</p></div><span class="date-label">3 października 2026</span></div><section class="account-surface" aria-label="Konto osobiste i dostępne środki"><div class="account-name">Konto osobiste</div><div class="account-number">28 0000 0000 0000 0000 0000 0482</div><div class="balance-label">Dostępne środki</div><div class="balance">${money(state.balance).replace(/ zł$/,'')} <span>PLN</span></div><div class="account-actions">${button(`Nowy przelew ${icon('arrow',17)}`,'new-transfer')}</div></section><section class="period-summary" aria-label="Podsumowanie miesiąca demonstracyjnego"><div><h2>Październik w skrócie</h2><p>Na podstawie operacji demo</p></div><dl><div><dt>Wpływy</dt><dd class="incoming">${money(incoming)}</dd></div><div><dt>Wydatki</dt><dd>${money(outgoing)}</dd></div></dl></section><div class="dashboard-bottom"><section class="transactions-region" aria-labelledby="recent-title"><div class="section-heading"><h2 id="recent-title">Ostatnie transakcje</h2><span>Dane przykładowe</span></div>${transactionTable(records.slice(0,5))}<button class="text-button ledger-link" data-route="history">Pełna historia ${icon('arrow',16)}</button></section><aside class="account-context"><h2>Twoje konto</h2><dl><div><dt>Właściciel</dt><dd>Anna · konto demo</dd></div><div><dt>Waluta rachunku</dt><dd>PLN</dd></div><div><dt>Rodzaj rachunku</dt><dd>Konto osobiste</dd></div></dl><div class="security-status">${icon('shield',22)}<div><strong>SafeTransfer · demo</strong><span>Ocena ryzyka jest niedostępna. Scenariusz wybierzesz w menu prototypu.</span></div></div><button class="text-button" data-action="help">Pomoc dotycząca konta ${icon('arrow',16)}</button></aside></div>`;
}
function transferView(){return `${bankNav('transfer')}<div class="transfer-heading"><h1 id="screen-title">Nowy przelew</h1><p class="screen-intro">Wprowadź dane odbiorcy. Sprawdzisz je w następnym kroku.</p>${progress(1)}</div><div class="transfer-columns"><form id="transfer-form" class="transfer-form" novalidate><div class="account-choice"><strong>Z konta osobistego</strong><span>${money(state.balance)}</span></div>${field('beneficiary','Nazwa odbiorcy','Np. Pracownia Forma','autocomplete="off" required maxlength="100"')}${field('account','Numer rachunku odbiorcy','26 cyfr numeru rachunku','inputmode="numeric" autocomplete="off" required maxlength="32" aria-describedby="account-help"')}<p class="field-help" id="account-help" ><span id="account-count">${state.transfer.account.replace(/\s/g,'').length}</span> / 26 cyfr · rachunek demonstracyjny</p><label class="field"><span>Kwota</span><div class="amount-input"><input id="amount" name="amount" inputmode="decimal" placeholder="0,00" value="${escapeHTML(state.transfer.amount)}" required><span>PLN</span></div></label>${field('title','Tytuł przelewu','Np. numer faktury','autocomplete="off" required maxlength="140"')}<p id="form-error" class="inline-error" role="alert" hidden></p><div class="form-actions"><button type="button" class="text-button" data-route="dashboard">Anuluj</button><button type="submit" class="primary-button">Sprawdź dane ${icon('arrow',18)}</button></div></form><aside class="source-document" aria-label="Przykładowa faktura"><div class="document-heading">${icon('document',20)} Faktura</div><p>Przepisz dane do formularza. Wszystkie dane są fikcyjne.</p><dl><dt>Odbiorca</dt><dd>Pracownia Forma</dd><dt>Rachunek</dt><dd class="document-account">12 3456 7890 1234 5678 9012 3456</dd><dt>Tytuł</dt><dd>Faktura FV/10/2026</dd></dl><div class="document-divider"></div><div>Do zapłaty</div><div class="invoice-amount">1 250,00 zł</div></aside></div>`;}
function reviewView(){return `${bankNav('transfer')}<button class="text-button back-button" data-route="transfer">${icon('back',17)} Edytuj dane</button><div class="transfer-heading"><h1 id="screen-title">Sprawdź swój przelew</h1><p class="screen-intro">Upewnij się, że odbiorca i kwota są poprawne.</p>${progress(2)}</div><dl class="review-list"><div><dt>Odbiorca</dt><dd>${escapeHTML(state.transfer.beneficiary)}</dd></div><div><dt>Rachunek</dt><dd>${escapeHTML(state.transfer.account)}</dd></div><div><dt>Tytuł</dt><dd>${escapeHTML(state.transfer.title)}</dd></div><div><dt>Kwota</dt><dd class="review-amount">${money(state.transfer.amount)}</dd></div></dl><p class="review-note">${state.scenario==='intervention'?'Wybrany scenariusz demo pokaże ostrzeżenie przed kodem potwierdzenia.':'Następnie wpiszesz kod potwierdzenia. To przelew demonstracyjny.'}</p><div class="form-actions"><button class="text-button" data-route="transfer">Zmień dane</button>${button(`Przejdź do potwierdzenia ${icon('arrow',18)}`,'continue-transfer')}</div>`;}
function warningView(){const t=state.transfer;const name=t.beneficiary||invoice.beneficiary;const amount=t.amount||invoice.amount;return `${bankNav('transfer')}<div class="warning-screen">${progress(3)}<div class="warning-title-icon">${icon('warning',29)}</div><h1 id="screen-title">Zatrzymaj się na chwilę.<br>Sprawdź, komu przelewasz.</h1><p class="warning-intro">Ktoś prosi Cię o pilny przelew na „bezpieczne konto”? To częsty schemat oszustwa. Przelew w tym prototypie czeka na Twoją decyzję.</p><div class="paused-transfer"><div><strong>${escapeHTML(name)}</strong><span>Przykładowa interwencja · przelew wstrzymany</span></div><span class="paused-amount">${money(amount)}</span></div><h2 class="warning-question">Czy ktoś jest teraz z Tobą na linii i poleca Ci wykonać ten przelew?</h2><div class="answer-buttons">${button('Tak, ktoś mnie instruuje','answer-yes','secondary','aria-pressed="false"')}${button('Nie, robię to samodzielnie','answer-no','secondary','aria-pressed="false"')}</div><div id="safety-response" class="safety-response" aria-live="polite" hidden></div><details class="warning-reasons"><summary>Dlaczego pojawia się ostrzeżenie?</summary><p>Przykładowe wyjaśnienie dla docelowej aplikacji:</p><div class="reason-row"><span>Odbiorca</span><strong>Pierwszy przelew</strong></div><div class="reason-row"><span>Sposób wpisywania</span><strong>Dłuższe przerwy i korekty</strong></div><p>Te obserwacje nie dowodzą oszustwa. W tym prototypie zostały wpisane jako dane demonstracyjne.</p></details><button class="text-button" data-action="cancel-transfer">Anuluj ten przelew</button><p class="contact-info">Jeśli masz wątpliwości, zakończ rozmowę i samodzielnie skontaktuj się z bankiem przez jego oficjalną aplikację lub stronę.</p></div>`;}
function confirmView(){return `${bankNav('transfer')}<div class="confirmation-screen">${progress(3)}<h1 id="screen-title">Potwierdź przelew</h1><p class="screen-intro">Sprawdź dane i wpisz kod demonstracyjny. Ten przelew nie wysyła pieniędzy.</p><dl class="review-list"><div><dt>Odbiorca</dt><dd>${escapeHTML(state.transfer.beneficiary)}</dd></div><div><dt>Rachunek</dt><dd>${escapeHTML(state.transfer.account)}</dd></div><div><dt>Kwota</dt><dd class="review-amount">${money(state.transfer.amount)}</dd></div></dl><form id="transfer-confirm-form" novalidate><label class="field-label" for="transfer-code">Kod potwierdzenia</label><input id="transfer-code" class="sms-input" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="4" aria-describedby="confirm-help form-error" required><p class="field-help" id="confirm-help">Użyj <strong>1234</strong>. Prototyp nie wysyła SMS.</p><p id="form-error" class="inline-error" role="alert" hidden></p><div class="form-actions"><button class="text-button" type="button" data-route="transfer">Edytuj dane</button><button class="primary-button" type="submit">Potwierdź przelew ${icon('check',19)}</button></div></form><button class="text-button" data-action="cancel-transfer">Anuluj przelew</button></div>`;}
function transactionRecords(){
  return [...state.history.map(t=>({name:t.beneficiary,note:t.title,date:'3 października 2026',month:10,amount:Number(t.amount.replace(',','.')),incoming:false,status:'Potwierdzony · demo'})),
    {name:'Wynagrodzenie',note:'Wpływ na konto',date:'1 października 2026',month:10,amount:7200,incoming:true,status:'Zaksięgowane · demo'},
    {name:'Czynsz za mieszkanie',note:'Przelew za październik',date:'1 października 2026',month:10,amount:2450,incoming:false,status:'Zaksięgowane · demo'},
    {name:'Księgarnia Kameralna',note:'Zakup książek',date:'30 września 2026',month:9,amount:89.90,incoming:false,status:'Zaksięgowane · demo'}];
}
function transactionTable(records=transactionRecords()){
  return `<table class="transactions" aria-label="Historia operacji demonstracyjnych"><thead><tr><th scope="col">Operacja</th><th scope="col">Kwota i status</th></tr></thead><tbody>${records.map(t=>`<tr><td><div class="transaction-name">${escapeHTML(t.name)}</div><div class="transaction-meta">${escapeHTML(t.note)}<br>${t.date}</div></td><td class="transaction-amount ${t.incoming?'incoming':''}">${t.incoming?'+':'−'}${money(t.amount)}<span class="transaction-status">${t.status}</span></td></tr>`).join('')}</tbody></table>`;
}
function normalizeSearch(value){return value.toLocaleLowerCase('pl-PL').normalize('NFD').replace(/\p{Diacritic}/gu,'').replace(/ł/g,'l').trim();}
function historyResults(){
  const query=normalizeSearch(state.historyQuery);const records=transactionRecords().filter(t=>normalizeSearch(`${t.name} ${t.note} ${t.date}`).includes(query));
  return `<p class="results-count" role="status">Liczba operacji: ${records.length}</p>${records.length?transactionTable(records):`<div class="empty-state"><h2>Brak pasujących operacji</h2><p>Spróbuj wpisać inną nazwę odbiorcy, tytuł lub datę.</p><button class="secondary-button" data-action="clear-history">Wyczyść wyszukiwanie</button></div>`}`;
}
function historyView(){return `${bankNav('history')}<h1 id="screen-title">Historia operacji</h1><p class="screen-intro">Sprawdź odbiorcę, kwotę i status. Lista zawiera fikcyjne transakcje oraz przelewy z bieżącej sesji.</p><div class="history-toolbar"><label class="field history-search"><span>Szukaj w historii</span><div class="search-control">${icon('search',19)}<input type="search" id="history-search" placeholder="Odbiorca, tytuł lub data" value="${escapeHTML(state.historyQuery)}" autocomplete="off" aria-controls="history-results"></div></label><p>Przykładowe dane · PLN</p></div><div class="transactions-region" id="history-results">${historyResults()}</div><div class="form-actions">${button('Wróć do konta','dashboard','secondary')}</div>`;}

function helpView(){return `<div class="help-screen"><button class="text-button back-button" data-route="${escapeHTML(state.returnRoute)}">${icon('back',17)} Wróć do poprzedniego ekranu</button><h1 id="screen-title">Jak możemy pomóc?</h1><p class="screen-intro">Krótka instrukcja korzystania z demonstracyjnego Bank24.</p><details class="help-topic" open><summary>Jak się zalogować?</summary><p>Użyj loginu <strong>anna.demo</strong>, hasła <strong>bank24</strong> i kodu <strong>1234</strong>. Przycisk „Uzupełnij dane demo” wpisze login i hasło. Wiadomość SMS nie jest wysyłana.</p></details><details class="help-topic"><summary>Jak wykonać przelew?</summary><p>Otwórz „Nowy przelew”, przepisz dane z fikcyjnej faktury i wybierz „Sprawdź dane”. Po podsumowaniu wpisz kod 1234. Przed potwierdzeniem możesz wrócić do edycji lub anulować przelew.</p></details><details class="help-topic"><summary>Czy kamera jest wymagana?</summary><p>Nie. Podgląd uruchamiasz po zgodzie i możesz go wyłączyć. Prototyp nie przesyła, nie nagrywa ani nie analizuje obrazu. Odmowa uprawnienia nie blokuje logowania ani przelewu.</p></details><details class="help-topic"><summary>Co zrobić, gdy ktoś nakłania mnie do przelewu?</summary><p>Przerwij rozmowę, anuluj przelew i samodzielnie zweryfikuj prośbę przez oficjalny kanał banku. W Bank24 możesz obejrzeć taki scenariusz przez menu „Ekrany prototypu”.</p></details><details class="help-topic"><summary>Co oznacza „Zapamiętaj urządzenie”?</summary><p>W prototypie to wyłącznie wybór przechowywany do wylogowania. Nie zapisujemy hasła ani tokenu urządzenia. W docelowej aplikacji funkcję obsłuży backend po potwierdzeniu logowania.</p></details></div>`;}
function resultView(){
  if(!state.result)return `${bankNav('transfer')}<h1 id="screen-title">Podgląd wyniku przelewu</h1><p class="screen-intro">Przygotuj przelew, aby obejrzeć jego potwierdzenie lub anulowanie.</p>${button('Przygotuj przelew','new-transfer')}`;
  const cancelled=state.result==='cancelled';const t=state.lastTransfer||state.transfer;
  return `${bankNav('dashboard')}<div class="result-screen"><div class="result-icon">${icon(cancelled?'shield':'check',30)}</div><h1 id="screen-title">${cancelled?'Przelew został anulowany':'Przelew demonstracyjny potwierdzony'}</h1><p class="screen-intro">${cancelled?'Żadne środki nie zostały wysłane. Możesz spokojnie zweryfikować sytuację.':'Kod został zaakceptowany. Saldo i historia zostały zaktualizowane wyłącznie w tej symulacji.'}</p><dl class="review-list"><div><dt>Odbiorca</dt><dd>${escapeHTML(t.beneficiary)}</dd></div><div><dt>Kwota</dt><dd class="review-amount">${money(t.amount)}</dd></div><div><dt>Status</dt><dd>${cancelled?'Anulowany':'Potwierdzony w demonstracji'}</dd></div></dl>${button(`Wróć do konta ${icon('arrow',18)}`,'dashboard')}<p class="demo-note">Bank24 nie wysyła pieniędzy. Stan demonstracji zostanie wyczyszczony po wylogowaniu.</p></div>`;
}
function setWarningAnswer(action){state.warningAnswer=action;document.querySelectorAll('.answer-buttons button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.action===action)));const el=document.querySelector('#safety-response');el.hidden=false;el.innerHTML=action==='answer-yes'?`<strong>Zakończ rozmowę i zweryfikuj prośbę.</strong><p>Nie przelewaj pieniędzy pod presją. Skontaktuj się z bankiem samodzielnie, przez znany Ci oficjalny kanał.</p><div class="form-actions">${button('Anuluj przelew','cancel-transfer')}${button('Wróć do konta','dashboard','secondary')}</div>`:`<strong>Sprawdź dane jeszcze raz.</strong><p>Jeśli przelew jest Twoją decyzją, upewnij się, że znasz odbiorcę. Przejdź do potwierdzenia kodem demonstracyjnym albo wróć do edycji.</p><div class="form-actions">${button('Edytuj przelew','edit-transfer','secondary')}${button('Przejdź do kodu SMS','confirm-transfer')}</div>`;}
function restoreClosedOperation(){
  const record=state.closedOperations.get(state.operationId);if(!record)return false;
  state.result=record.result;state.lastTransfer={...record.transfer};return true;
}
function startOperation(transfer){state.operationId++;state.result=null;state.lastTransfer=null;state.warningAnswer=null;state.transfer={...transfer};}
function closeOperation(result){
  if(restoreClosedOperation())return;
  const transfer={...state.transfer};state.closedOperations.set(state.operationId,{result,transfer});state.result=result;state.lastTransfer=transfer;
  if(result==='finished'){state.balance-=Number(transfer.amount.replace(',','.'));state.history.unshift(transfer);}
}
function formError(message,id){
  screen.querySelectorAll('[aria-invalid]').forEach(input=>input.removeAttribute('aria-invalid'));
  const el=screen.querySelector('#form-error');el.textContent=message;el.hidden=false;
  const input=id?screen.querySelector(`#${id}`):null;
  if(input){input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',[...new Set((input.getAttribute('aria-describedby')||'').split(' ').filter(Boolean).concat('form-error'))].join(' '));const field=input.closest('.field');(field||input).insertAdjacentElement('afterend',el);input.focus();}
}
function transferError(t){
  if(!t.beneficiary.trim())return ['Wpisz nazwę odbiorcy.','beneficiary'];
  if(!/^\d{26}$/.test(t.account.replace(/\s/g,'')))return ['Wpisz 26 cyfr numeru rachunku. Spacje są dozwolone.','account'];
  const raw=t.amount.trim();
  if(!/^\d+(?:[,.]\d{1,2})?$/.test(raw)||Number(raw.replace(',','.'))<=0)return ['Wpisz kwotę większą od zera, np. 1250,00.','amount'];
  if(Number(raw.replace(',','.'))>state.balance)return ['Kwota przekracza dostępne środki na fikcyjnym koncie.','amount'];
  if(!t.title.trim())return ['Wpisz tytuł przelewu.','title'];
  return null;
}
function commitDemoTransition(form,route,commit=()=>{}){
  form.setAttribute('aria-busy','true');const submit=form.querySelector('[type="submit"]');submit.disabled=true;submit.textContent='Sprawdzanie danych demo…';
  const status=document.createElement('p');status.className='form-status';status.setAttribute('role','status');status.textContent='Trwa potwierdzanie w symulacji.';form.append(status);
  window.setTimeout(()=>{if(form.isConnected){commit();navigate(route);}},250);
}
function onSubmit(event){
  event.preventDefault();const form=event.currentTarget;if(form.getAttribute('aria-busy')==='true')return;const data=new FormData(form);
  if(form.id==='login-form'){
    state.credentials={login:String(data.get('login')).trim(),password:String(data.get('password'))};
    if(state.credentials.login!=='anna.demo'){formError('Użyj loginu demonstracyjnego anna.demo.','login-input');return;}
    if(state.credentials.password!=='bank24'){formError('Użyj hasła demonstracyjnego bank24.','password');return;}
    state.remember=!!data.get('remember');commitDemoTransition(form,'sms');
  }
  if(form.id==='sms-form'){
    if(data.get('code')!=='1234'){formError('Kod demonstracyjny to 1234. Sprawdź kod i spróbuj ponownie.','sms-code');return;}
    commitDemoTransition(form,'dashboard');
  }
  if(form.id==='transfer-form'){
    if(restoreClosedOperation()){navigate('result');return;}
    state.transfer=Object.fromEntries(data.entries());const error=transferError(state.transfer);if(error){formError(...error);return;}navigate('review');
  }
  if(form.id==='transfer-confirm-form'){
    if(restoreClosedOperation()){navigate('result');return;}
    if(transferError(state.transfer)){navigate('transfer');toast('Uzupełnij poprawne dane przelewu przed potwierdzeniem.');return;}
    if(data.get('code')!=='1234'){formError('Kod demonstracyjny to 1234. Sprawdź kod i spróbuj ponownie.','transfer-code');return;}
    commitDemoTransition(form,'result',()=>closeOperation('finished'));
  }
}
function resetSession(){state.operationId=1;state.closedOperations.clear();state.balance=18420.50;state.history=[];state.historyQuery='';state.lastTransfer=null;state.credentials={login:'',password:''};state.remember=false;state.transfer={beneficiary:'',account:'',amount:'',title:''};state.warningAnswer=null;state.result=null;stopCamera();document.querySelector('#camera-parameters').open=false;navigate('login');}
function stopCamera(){state.cameraRequest++;state.cameraPending=false;document.querySelector('#camera-toggle').disabled=false;const confirm=document.querySelector('[data-action="camera-confirm"]');confirm.disabled=false;confirm.textContent='Uruchom podgląd';state.stream?.getTracks().forEach(track=>track.stop());state.stream=null;document.querySelector('#local-video').srcObject=null;document.querySelector('#local-video').hidden=true;document.querySelector('#camera-placeholder').hidden=false;document.querySelector('#camera-status').textContent='Kamera wyłączona';document.querySelector('#camera-status').classList.remove('active');document.querySelector('#camera-toggle').innerHTML=icon('camera',16)+' Włącz kamerę';document.querySelector('#camera-consent').hidden=true;document.querySelector('#camera-agreement').checked=false;}
async function startCamera(){
  if(state.cameraPending)return;
  const error=document.querySelector('#camera-error');error.hidden=true;
  if(!document.querySelector('#camera-agreement').checked){error.textContent='Zaznacz zgodę, aby uruchomić lokalny podgląd.';error.hidden=false;return;}
  const request=++state.cameraRequest;state.cameraPending=true;
  const control=document.querySelector('#camera-toggle');const confirm=document.querySelector('[data-action="camera-confirm"]');
  control.disabled=true;confirm.disabled=true;confirm.textContent='Uruchamianie…';
  try{
    if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw new Error('Otwórz prototyp przez localhost lub HTTPS, aby włączyć kamerę.');
    const stream=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    if(request!==state.cameraRequest){stream.getTracks().forEach(track=>track.stop());return;}
    state.stream=stream;const video=document.querySelector('#local-video');video.srcObject=stream;video.hidden=false;
    document.querySelector('#camera-placeholder').hidden=true;document.querySelector('#camera-status').textContent='Podgląd aktywny';document.querySelector('#camera-status').classList.add('active');
    control.innerHTML=icon('camera',16)+' Wyłącz kamerę';document.querySelector('#camera-consent').hidden=true;
    stream.getVideoTracks()[0].addEventListener('ended',()=>{if(state.stream===stream){stopCamera();toast('Podgląd został zatrzymany. Możesz ponownie włączyć kamerę.');}},{once:true});
  }catch(e){
    if(request!==state.cameraRequest)return;
    stopCamera();error.textContent=({NotAllowedError:'Nie udzielono dostępu do kamery. Możesz kontynuować bez niej lub zmienić uprawnienia przeglądarki.',NotFoundError:'Nie znaleziono kamery. Możesz kontynuować bez podglądu.',NotReadableError:'Kamera jest zajęta. Zamknij inną aplikację korzystającą z kamery i spróbuj ponownie.'})[e.name]||e.message;error.hidden=false;
  }finally{if(request===state.cameraRequest||!state.cameraPending){state.cameraPending=false;control.disabled=false;confirm.disabled=false;confirm.textContent='Uruchom podgląd';}}
}
document.addEventListener('click',event=>{if(event.target.closest('.skip-link')){event.preventDefault();screen.focus();return;}const target=event.target.closest('[data-route],[data-action]');if(!target)return;if(target.dataset.route){navigate(target.dataset.route);return;}const action=target.dataset.action;
  if(action==='fill-demo'){document.querySelector('#login-input').value='anna.demo';document.querySelector('#password').value='bank24';state.credentials={login:'anna.demo',password:'bank24'};document.querySelector('#form-error').hidden=true;document.querySelectorAll('#login-form [aria-invalid]').forEach(input=>input.removeAttribute('aria-invalid'));document.querySelector('#login-form button[type=submit]').focus();}
  if(action==='password'){const input=document.querySelector('#password');const show=input.type==='password';input.type=show?'text':'password';target.setAttribute('aria-label',show?'Ukryj hasło':'Pokaż hasło');target.setAttribute('aria-pressed',String(show));}
  if(action==='help'||action==='forgot'){if(location.hash!=='#help')state.returnRoute=location.hash.slice(1)||'login';navigate('help');}
  if(action==='resend'){const note=document.querySelector('#sms-help');note.textContent='Kod demonstracyjny nadal wynosi 1234. SMS nie został wysłany.';note.setAttribute('role','status');}
  if(action==='new-transfer'){startOperation({beneficiary:'',account:'',amount:'',title:''});navigate('transfer');}
  if(action==='clear-history'){state.historyQuery='';document.querySelector('#history-search').value='';document.querySelector('#history-results').innerHTML=historyResults();document.querySelector('#history-search').focus();}
  if(action==='dashboard')navigate('dashboard');
  if(action==='logout')resetSession();
  if(action==='continue-transfer'){const error=transferError(state.transfer);if(error){navigate('transfer');return;}state.warningAnswer=null;navigate(state.scenario==='intervention'?'warning':'confirm');}
  if(action==='camera'){if(state.stream)stopCamera();else{document.querySelector('#camera-consent').hidden=false;document.querySelector('#camera-agreement').focus();}}
  if(action==='camera-confirm')startCamera();
  if(action==='camera-cancel'){stopCamera();document.querySelector('#camera-consent').hidden=true;document.querySelector('#camera-error').hidden=true;}
  if(action==='answer-yes'||action==='answer-no')setWarningAnswer(action);
  if(action==='cancel-transfer'){closeOperation('cancelled');navigate('result');}
  if(action==='confirm-transfer')navigate('confirm');
  if(action==='edit-transfer')navigate('transfer');
});
document.addEventListener('input',event=>{if(event.target.id==='history-search'){state.historyQuery=event.target.value;document.querySelector('#history-results').innerHTML=historyResults();}if(event.target.hasAttribute('aria-invalid')){event.target.removeAttribute('aria-invalid');const error=screen.querySelector('#form-error');if(error)error.hidden=true;}if(event.target.closest('#login-form')&&['login','password'].includes(event.target.name))state.credentials[event.target.name]=event.target.value;if(event.target.closest('#transfer-form')&&event.target.name in state.transfer){if(state.closedOperations.has(state.operationId))startOperation(state.transfer);state.transfer[event.target.name]=event.target.value;if(event.target.name==='account')document.querySelector('#account-count').textContent=event.target.value.replace(/\s/g,'').length;}});
document.addEventListener('change',event=>{if(event.target.id==='remember')state.remember=event.target.checked;if(event.target.name==='scenario')state.scenario=event.target.value;});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.querySelector('#prototype-menu').open){document.querySelector('#prototype-menu').open=false;document.querySelector('#prototype-menu > summary').focus();}});
window.addEventListener('hashchange',()=>render(location.hash.slice(1)));
window.addEventListener('pagehide',stopCamera);
document.querySelector('#safe-brand').innerHTML=icon('shield',17)+'<span>SafeTransfer · demo</span>';
document.querySelector('#camera-symbol').innerHTML=icon('camera',21);
document.querySelector('#placeholder-icon').innerHTML=icon('camera',43);
document.querySelector('#parameter-chevron').innerHTML=icon('chevron',18);
document.querySelector('#camera-toggle').innerHTML=icon('camera',16)+' Włącz kamerę';
document.querySelector('#privacy-note').innerHTML=icon('lock',15)+'<span>Obraz pozostaje w tej przeglądarce. Logowanie i przelew są dostępne również bez kamery.</span>';
const cameraBreakpoint=window.matchMedia('(min-width:1024px)');
document.querySelector('#camera-body').open=cameraBreakpoint.matches;
cameraBreakpoint.addEventListener('change',event=>document.querySelector('#camera-body').open=event.matches);
render(location.hash.slice(1)||'login',false);
