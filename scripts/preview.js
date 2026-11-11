// 生成体验二维码到 docs/preview-qrcode.jpg，面板上可直接扫码。
// 需要先在仓库 Secrets 配 WECHAT_APPID 与 WECHAT_PRIVATE_KEY（密钥文件内容）。
const fs = require('fs');
const os = require('os');
const path = require('path');
const ci = require('miniprogram-ci');

const key = process.env.WECHAT_PRIVATE_KEY;
const appid = process.env.WECHAT_APPID;
if (!key || !appid) {
  console.error('缺少 WECHAT_APPID / WECHAT_PRIVATE_KEY');
  process.exit(1);
}
const keyPath = path.join(os.tmpdir(), 'mp-private.key');
fs.writeFileSync(keyPath, key, { mode: 0o600 });
fs.mkdirSync('docs', { recursive: true });

// 若用 Taro / uni-app，把 projectPath 改成构建产物目录（如 dist/build/mp-weixin）
const project = new ci.Project({
  appid,
  type: 'miniProgram',
  projectPath: process.cwd(),
  privateKeyPath: keyPath,
  ignores: ['node_modules/**/*', '.git/**/*', '.github/**/*', 'scripts/**/*', 'docs/**/*'],
});

(async () => {
  await ci.preview({
    project,
    desc: 'flow 自动预览',
    setting: { es6: true, minified: true },
    qrcodeFormat: 'image',
    qrcodeOutputDest: 'docs/preview-qrcode.jpg',
  });
  console.log('二维码已生成：docs/preview-qrcode.jpg');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
