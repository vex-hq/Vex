import { createCanvas, loadImage } from 'canvas';
import { writeFileSync } from 'fs';

const WIDTH = 1200;
const HEIGHT = 630;

const canvas = createCanvas(WIDTH, HEIGHT);
const ctx = canvas.getContext('2d');

// Dark background
ctx.fillStyle = '#0a0a0a';
ctx.fillRect(0, 0, WIDTH, HEIGHT);

// Load and draw the triangle mark
const logo = await loadImage('vex-design-kit/png/logo/vex-logo-transparent-dark-512.png');
const logoSize = 160;
const logoX = (WIDTH / 2) - logoSize / 2;
const logoY = 140;
ctx.drawImage(logo, logoX, logoY, logoSize, logoSize);

// "Vex" title
ctx.fillStyle = '#ffffff';
ctx.font = 'bold 72px sans-serif';
ctx.textAlign = 'center';
ctx.fillText('Vex', WIDTH / 2, 380);

// Tagline
ctx.fillStyle = '#999999';
ctx.font = '32px sans-serif';
ctx.fillText('Agent reliability infrastructure', WIDTH / 2, 430);

// Domain
ctx.fillStyle = '#666666';
ctx.font = '24px sans-serif';
ctx.fillText('tryvex.dev', WIDTH / 2, 520);

const buffer = canvas.toBuffer('image/png');
writeFileSync('Dashboard/apps/landing/public/images/og-image.png', buffer);
console.log('Generated og-image.png (1200x630)');
