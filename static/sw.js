const CACHE='powerhouse-v74-3-livefix3';
const ASSETS=['/static/icon-192.png','/static/icon-512.png','/static/apple-touch-icon.png','/static/manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(u.pathname.startsWith('/api/')) return;
  if(e.request.mode==='navigate'||u.pathname==='/'||u.pathname==='/static/v743.html'||u.pathname==='/static/sw.js'){
    e.respondWith(fetch(e.request,{cache:'no-store'})); return;
  }
  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));
});
self.addEventListener('push',event=>{let p={};try{p=event.data?event.data.json():{}}catch(_){p={body:event.data?event.data.text():'POWERHOUSE AI alert'}}const title=p.title||'POWERHOUSE AI V74.3';const options={body:p.body||'New precision alert',icon:'/static/icon-192.png',badge:'/static/icon-192.png',tag:p.tag||('powerhouse-'+(p.priority||'alert')),renotify:true,data:{url:p.url||'/'},actions:[{action:'open',title:'Open POWERHOUSE'}]};event.waitUntil(self.registration.showNotification(title,options));});
self.addEventListener('notificationclick',event=>{event.notification.close();const url=(event.notification.data&&event.notification.data.url)||'/';event.waitUntil(clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{for(const c of list){if('focus'in c){c.navigate(url);return c.focus()}}return clients.openWindow?clients.openWindow(url):undefined}));});
