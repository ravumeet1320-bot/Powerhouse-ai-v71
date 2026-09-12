const CACHE='powerhouse-v72-2-timing-execution-2';
const SHELL=['/','/manifest.webmanifest','/static/icon-192.png','/static/icon-512.png','/static/apple-touch-icon.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if(u.pathname.startsWith('/api/')) return;
  if(e.request.mode==='navigate'){
    e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put('/',copy));return r;}).catch(()=>caches.match('/')));
    return;
  }
  e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));
});
