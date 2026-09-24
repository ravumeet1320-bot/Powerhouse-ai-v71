// V74.8 visible-brand hotfix. Add this script at the end of static/v748.html if not already included.
(function(){
  function apply(){
    document.title='POWERHOUSE AI V74.8 — Move Intelligence + Expiry Hero';
    const ver=document.querySelector('.tag.ver');
    if(ver) ver.textContent='V74.8';
    const master=document.querySelector('.tag.master');
    if(master) master.textContent='MOVE INTELLIGENCE + EXPIRY HERO';
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',apply);
  else apply();
})();
