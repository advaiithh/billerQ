/**
 * BillerQ Static Server
 * Serves the React build correctly — handles SPA routing (React Router).
 * 
 * Run: node serve.js
 * Open: http://localhost:3000
 */

const http = require('http');
const fs   = require('fs');
const path = require('path');

const PORT    = 3000;
const ROOT    = __dirname; // The build/ folder

const MIME = {
  '.html': 'text/html',
  '.js':   'application/javascript',
  '.css':  'text/css',
  '.json': 'application/json',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
  '.svg':  'image/svg+xml',
  '.woff': 'font/woff',
  '.woff2':'font/woff2',
  '.ttf':  'font/ttf',
  '.txt':  'text/plain',
  '.map':  'application/json',
  '.webp': 'image/webp',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
};

const server = http.createServer((req, res) => {
  // Strip query string
  let urlPath = req.url.split('?')[0];

  // Resolve to filesystem path
  let filePath = path.join(ROOT, urlPath);

  // Check if file exists
  if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
    // Serve the file directly
    const ext  = path.extname(filePath).toLowerCase();
    const mime = MIME[ext] || 'application/octet-stream';

    res.writeHead(200, { 'Content-Type': mime });
    fs.createReadStream(filePath).pipe(res);
  } else {
    // SPA fallback — serve index.html for all unknown routes
    // This lets React Router handle /customers, /payments, etc.
    const indexPath = path.join(ROOT, 'index.html');
    res.writeHead(200, { 'Content-Type': 'text/html' });
    fs.createReadStream(indexPath).pipe(res);
  }
});

server.listen(PORT, () => {
  console.log('');
  console.log('  ╔══════════════════════════════════════╗');
  console.log('  ║   BillerQ is running!                ║');
  console.log('  ║                                      ║');
  console.log(`  ║   http://localhost:${PORT}             ║`);
  console.log('  ║                                      ║');
  console.log('  ║   Press Ctrl+C to stop               ║');
  console.log('  ╚══════════════════════════════════════╝');
  console.log('');
});
