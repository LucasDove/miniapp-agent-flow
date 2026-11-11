// 上传开发版到微信公众平台「开发版本」列表；提审仍需人工在后台点。
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

const project = new ci.Project({
  appid,
  type: 'miniProgram',
  projectPath: process.cwd(),
  privateKeyPath: keyPath,
  ignores: ['node_modules/**/*', '.git/**/*', '.github/**/*', 'scripts/**/*', 'docs/**/*'],
});

(async () => {
  await ci.upload({
    project,
    version: process.env.FLOW_VERSION || '0.0.1',
    desc: 'flow 自动上传',
    setting: { es6: true, minified: true },
  });
  console.log('已上传到开发版本列表，去公众平台版本管理页查看');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
