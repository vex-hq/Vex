import { createCanvas, loadImage } from 'canvas';
import { writeFileSync, mkdirSync } from 'fs';

const WIDTH = 1280;
const HEIGHT = 320;

const canvas = createCanvas(WIDTH, HEIGHT);
const ctx = canvas.getContext('2d');

// Dark background
ctx.fillStyle = '#0a0a0a';
ctx.fillRect(0, 0, WIDTH, HEIGHT);

// Load and draw the triangle mark (left of center)
const logo = await loadImage('vex-design-kit/png/logo/vex-logo-transparent-dark-512.png');
const logoSize = 140;
const centerX = WIDTH / 2;
const logoX = centerX - 180;
const logoY = (HEIGHT - logoSize) / 2;
ctx.drawImage(logo, logoX, logoY, logoSize, logoSize);

// "Vex" title (right of mark)
ctx.fillStyle = '#ffffff';
ctx.font = 'bold 64px sans-serif';
ctx.textAlign = 'left';
const textX = centerX - 20;
ctx.fillText('Vex', textX, HEIGHT / 2 - 10);

// Tagline
ctx.fillStyle = '#999999';
ctx.font = '26px sans-serif';
ctx.fillText('Agent reliability infrastructure', textX, HEIGHT / 2 + 30);

mkdirSync('docs/images', { recursive: true });
const buffer = canvas.toBuffer('image/png');
writeFileSync('docs/images/vex-readme-banner.png', buffer);
console.log('Generated vex-readme-banner.png (1280x320)');
