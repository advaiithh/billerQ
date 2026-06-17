// public/firebase-messaging-sw.js
importScripts("https://www.gstatic.com/firebasejs/9.0.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/9.0.0/firebase-messaging-compat.js");

firebase.initializeApp({
 apiKey: "AIzaSyBd57APd4jUGLYzsc-nywyqc6xGkQP7SPE",
  authDomain: "watercrm.firebaseapp.com",
  projectId: "watercrm",
  storageBucket: "watercrm.firebasestorage.app",
  messagingSenderId: "919125815470",
  appId: "1:919125815470:web:e7fb4db65b448f0db43d3f",
  measurementId: "G-HYKFY3DHC2"
});

const messaging = firebase.messaging();

self.addEventListener('notificationclick', function(event) {
  event.notification.close();

  event.waitUntil(
    (async () => {
      // 1. Log to confirm event fired
      console.log('=== NOTIFICATION CLICKED ===');
      console.log('Origin:', self.location.origin);

      const urlToOpen = 'http://localhost:3000/complaints'; // 👈 change your port

      // 2. Log all open clients
      const clientList = await clients.matchAll({ 
        type: 'window', 
        includeUncontrolled: true 
      });
      console.log('Open clients count:', clientList.length);
      clientList.forEach(c => console.log('Client URL:', c.url));

      // 3. Try focus existing tab
      for (let client of clientList) {
        if (client.url.startsWith(urlToOpen)) {
          console.log('Focusing existing tab...');
          return await client.focus();
        }
      }

      // 4. Try open new window
      console.log('Opening new window:', urlToOpen);
      try {
        const result = await clients.openWindow(urlToOpen);
        console.log('openWindow result:', result);
      } catch (err) {
        console.error('openWindow FAILED:', err); // 👈 this will tell you exact error
      }
    })()
  );
});