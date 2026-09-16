(()=>{
 const THEME_KEY='powerhouseTheme';
 const $=id=>document.getElementById(id);
 function applyTheme(theme){
   const t=theme==='dark'?'dark':'light'; document.documentElement.dataset.theme=t; localStorage.setItem(THEME_KEY,t);
   const icon=$('themeIcon'),label=$('themeLabel'),meta=document.querySelector('meta[name="theme-color"]');
   if(icon) icon.textContent=t==='dark'?'☀':'☾'; if(label) label.textContent=t==='dark'?'LIGHT':'DARK'; if(meta) meta.content=t==='dark'?'#07101c':'#f8f7ff';
 }
 function boot(){
   const status=$('statusBtn');
   if(status && !$('themeToggle')){
     const wrap=document.createElement('div'); wrap.className='topActions';
     const btn=document.createElement('button'); btn.className='themeToggle'; btn.id='themeToggle'; btn.type='button'; btn.setAttribute('aria-label','Toggle light or dark mode'); btn.innerHTML='<span id="themeIcon">☾</span><b id="themeLabel">DARK</b>';
     const parent=status.parentNode; parent.insertBefore(wrap,status); wrap.append(btn,status);
     btn.addEventListener('click',()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
   }
   applyTheme(localStorage.getItem(THEME_KEY)||'light');
   const v63=document.querySelector('#page-v63 .v56Sub'); if(v63) v63.textContent="Pro-grade market overview + today's strongest sector + top gainer + verified macro/global cues. Dead or unverified feeds are hidden automatically.";
   const v63Safe=document.querySelector('#page-v63 .safe'); if(v63Safe) v63Safe.textContent='Only working numeric feeds are shown. India VIX / crude / FX / gold / US indices come from authenticated Upstox when available. US Treasury yield cards are shown only when a configured/verified daily source returns a numeric value. Unavailable cards are removed — never faked.';
   const v62Title=document.querySelector('#page-v62 .v56Title'); if(v62Title) v62Title.textContent='Consolidated Market Intelligence • Global Macro OS';
   const cleanGlobal=()=>{
     ['v63US10Y','v63Curve'].forEach(id=>{const el=$(id);const tile=el?.closest('.v54Stat');if(tile){const missing=!el.textContent||['—','N/A','UNAVAILABLE'].includes(el.textContent.trim().toUpperCase());tile.style.display=missing?'none':'';}});
     const gm=$('v63GlobalMarkets'); if(gm){[...gm.children].forEach(card=>{const txt=(card.textContent||'').toUpperCase(); if(txt.includes('UNAVAILABLE')||txt.includes('DATA ERROR')) card.style.display='none';});}
   };
   cleanGlobal(); new MutationObserver(cleanGlobal).observe(document.body,{subtree:true,childList:true,characterData:true});
 }
 if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
