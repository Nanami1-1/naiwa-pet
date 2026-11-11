# 桌宠 · 奶蛙

一只会盯着你看、能拖着甩、会自己溜达的黄色团子。Python + PySide6，透明置顶窗口，跑在你的桌面上。

## 怎么跑

桌面上有个「桌宠」图标，双击就行（图标就是它的头）。

也可以：

- 双击项目里的 `run.bat`（无控制台窗口）
- 命令行 `pip install PySide6` 后 `python main.py`

想退出：右键它 → 退出。

> `.bat` 在 Windows 上不能挂自定义图标——图标只属于 exe / lnk / ico。
> 所以桌面那个是 `.lnk` 快捷方式，指向 `run.bat`，双击行为一模一样。
> 想重新生成：`python tools/make_icon.py` 然后 `python tools/make_shortcut.py`。

## 能干什么

| 操作 | 反应 |
|---|---|
| 按住拖动 | 跟着鼠标走，甩得快会拉长、身体倾斜，松开手带惯性飞出去 |
| 松手落地 | 撞地面回弹、挤压再弹回原状，撞屏幕左右边缘会掉头 |
| 单击 | 蹦一下 + 冒气泡说话，连点五次以上会生气 |
| 双击 | 原地转一圈 |
| 鼠标靠近 | 瞳孔跟着你转，身体微微朝你偏 |
| 长时间不动 | 自己小范围溜达，走的时候左右摇摆，随机小跳 |
| 鼠标停在它身上 | 头顶弹出饱食度 / 好感度小药丸 |
| 右键 | 喂食 / 摸摸头 / 让它睡会儿 / 别乱跑 / 静音 / 退出 |

饿到 28 以下会自己念叨「咕……」，心情和好感度会随时间和互动变化。

## 目录

```
├── main.py                 启动入口
├── run.bat                 Windows 双击启动
├── config.py              所有手感参数（尺寸、重力、速度、文案、配色）
├── core/
│   ├── sprite.py          加载精灵图、绘制、形变、命中检测
│   ├── motion.py          物理、状态机、形变曲线
│   ├── needs.py           饱食度 / 好感度 / 精力
│   └── sfx.py             音效查找与播放
├── ui/
│   ├── window.py          透明置顶窗口、鼠标交互、右键菜单
│   └── bubble.py          头顶气泡 + 状态药丸
├── assets/
│   ├── pet_base.png       抠好的透明精灵图
│   ├── pet_blink.png      眨眼
│   ├── pet_happy.png      开心（弯眼）
│   ├── pet_angry.png      生气（瞪眼）
│   ├── pet_sleep.png      睡着
│   ├── pet_eye_near.png   虹膜底板（抹掉瞳孔，用来叠可动瞳孔）
│   ├── pet.ico            桌面图标（7 种尺寸）
│   ├── eyes.json          眼睛坐标元数据
│   └── sounds/            音效
└── tools/
    ├── build_assets.py    从原图重新生成素材
    ├── make_icon.py       从精灵图剪头像做成 .ico
    ├── make_shortcut.py   在桌面创建带图标的快捷方式
    ├── render_preview.py  不开窗口，导出各姿态对照图
    ├── check_sound.py     逐个试放音效，打印「事件 → 文件 → 时长」
    ├── normalize_sounds.py 批量去掉音效首尾静音，转成 wav
    ├── trim_audio.py      截取音频片段，输出 16bit wav
    ├── build_exe.py       打包成免安装 exe + zip
    └── test_drag.py       端到端拖动测试
```

> `run.bat` 是 GBK 编码。别用编辑器把它另存成 UTF-8，否则 cmd 会把中文注释读成乱码并报「不是内部或外部命令」。

## 打包给别人用

```bash
python tools/build_exe.py
```

出来三样东西：

```
dist/Blobby/Blobby.exe      双击即用，对方不需要装 Python
dist/Blobby/assets/         素材和音效，可以随时替换
dist/Blobby-win64.zip       发这个给别人，解压后双击 exe
```

用的是 onedir（文件夹）而不是 onefile（单文件），因为 onefile 每次启动都要把 Qt 解压到临时目录，要等好几秒；文件夹版秒开，而且音效素材是独立目录，对方想换直接丢进去。

**几个要提前知道的**

- 对方第一次运行可能弹「Windows 已保护你的电脑」——因为 exe 没做代码签名，点「更多信息 → 仍要运行」即可。要彻底消除得买证书。
- 别把 `assets` 文件夹和 exe 分开，缺了会弹「桌宠启动失败」并指出缺哪个文件。
- 改完代码或素材要重新跑一次构建，`dist/` 会被整个覆盖。
- 只想出单文件版：把 `build_exe.py` 里 `--windowed` 后面加个 `--onefile`，再把 `copy_assets` 改成用 `--add-data` 塞进去。启动会慢 2~5 秒。


## 自动更新

奶蛙启动 5 秒后会安静地问一句 GitHub「最新版是多少」，一天最多一次。

- 有新版本 → 冒气泡提醒，右键菜单里变成「更新到 vX.Y.Z」
- 点它 → 确认框（带更新说明）→ 下载 → SHA-256 校验 → 解压 → 重启换上
- 下载时显示进度窗口，包含百分比、已下载大小和总大小；校验、解压时显示当前阶段。
- 收起进度窗口后继续下载，右键「查看更新进度」可重新打开；失败时窗口显示具体原因。
- 已经是最新 → 什么都不说（手动点「检查更新」才回「已经是最新的啦」）
- 连不上网 → 静默跳过，绝不影响正常用

更新源两个，按顺序试：GitHub Releases API → jsDelivr 上的 `version.json`（国内兜底）。

### 它怎么在不覆盖自己的情况下换掉自己

Windows 不允许覆盖正在运行的 exe，所以流程是四步：

1. 新版本下载到 `<程序目录>/_update/package.zip`，校验 SHA-256，解压到 `_update/pkg/`
2. 主程序用 `--apply-update` 参数启动**解压出来的新 exe**，然后自己退出
3. 新 exe 进入助手模式：等旧进程消失、等单实例锁释放 → 备份旧 `Blobby.exe` → 覆盖文件 → 拉起新程序
4. 新程序启动 25 秒后清理 `_update/`

第 3 步的存活检查是真的：拉起来之后等 8 秒，进程没了就回滚旧版本再拉起。日志写在程序目录的 `update.log`。

**不会覆盖你改过的音效。** `assets/sounds/custom/` 下已存在的文件会跳过，新增的才写。

**装到只读目录（比如 Program Files）会自动降级**成打开下载页手动更新。

### 改版本号

只改 `version.py` 一处。当前版本显示在右键菜单底部。

检查记录在 `%APPDATA%\NaiwaPet\update_state.json`，删掉等于重置。

### 发新版流程

```bash
python tools/build_exe.py --version 1.2.0
```

脚本会先改写 `version.py`、再打包，最后生成 `version.json`。然后：

```bash
git add version.py version.json
git commit -m "v1.2.0"
git tag v1.2.0
git push && git push --tags
```

再去 GitHub 建 Release、把 tag 选 `v1.2.0`、附件传 `dist/Blobby-win64.zip`。**发布那一刻所有人的奶蛙就知道了**，不需要你推送到客户端。

> 版本号必须真的往上走。忘了改就会出现「永远提示有新版」或者「永远收不到更新」。

## 双击没反应怎么办

最常见的原因是**系统里不止一个 Python，PATH 上排第一的那个没装 PySide6**。

`run.bat` 启动前会挨个试：先试 PATH 里的 `pythonw`，不行再试项目开发时用的那个解释器，两个都 `import PySide6` 失败才会停下并提示。看到提示就按它说的装一次：

```
python -m pip install PySide6
```

另一个可能：它其实已经在跑了，只是被别的窗口挡住。程序是单实例的，重复点图标不会开第二只——先看看屏幕底部、任务栏上沿有没有它。

## 换素材

把新图放到 `pet/source.jpg`，然后：

```bash
python tools/build_assets.py
```

它会自动抠图、定位眼睛、重新生成五张表情图和音效。眼睛是按「大只绿色虹膜 + 远处一道竖缝」识别的，换成别的角色需要改 `detect_eyes()`。

想加新表情：在 `build_assets.py` 的 `main()` 里加一条 `paint_lid(...)` 调用生成 `pet_xxx.png`，再在 `core/motion.py` 的 `pose()` 里把 `variant` 设成 `"xxx"`。

## 加音效

把音频丢进 `assets/sounds/custom/`，命名成下面对应的英文名或中文名都行（wav / mp3 / ogg / m4a / flac）：

| 事件 | 中文文件名也可以用 | 什么时候响 |
|---|---|---|
| `tap` | 点击 / 戳 / 单击 | 单击蹦一下 |
| `tap_many` | 生气 / 抗议 / 连点 | 连点五次以上 |
| `drag` | 拖动 / 拎起 | 开始拖 |
| `land` | 落地 / 掉下 | 落地、撞墙 |
| `pet` | 摸头 / 摸摸 / 抚摸 | 右键摸摸头 |
| `feed` | 喂食 / 吃 / 吃东西 | 右键喂食 |
| `hungry` | 饿 / 饿了 | 饿了念叨 |
| `sleep` | 睡觉 / 睡着 | 睡着 |
| `wake` | 起床 / 叫醒 | 被叫醒；**睡着时不管点它、拖它还是喂它，都只响这一声** |
| `spin` | 转圈 / 转圈圈 | 双击转圈 |

音效有优先级：`wake`(95) > `tap_many`(90) > 其他（10~40）。达到 90 的音效播放期间**独占声道**，直到整段音频放完才允许别人响——所以叫醒声和连点抗议声不会被后一下点击切断，代价是这段时间里其他音效全静音。

也可以不用改名，直接在 `assets/sounds/custom/sounds.json` 里写映射：

```json
{ "tap": "我的点击音.mp3", "feed": "吧唧.wav" }
```

没提供的会回落到 `assets/sounds/` 里的内置合成音。

### 素材太长就截一段

下下来的音效经常是十几秒的预览，直接当点击音会拖沓。用这个截：

```bash
# 从第 0.27 秒开始，截 1.62 秒，输出 wav
python tools/trim_audio.py assets/sounds/custom/tap.mp3 assets/sounds/custom/tap.wav 0.27 1.62
```

懒得手动找位置就用批量归一化，它会自动去掉首尾静音并统一转成 wav：

```bash
python tools/normalize_sounds.py          # 真跑
python tools/normalize_sounds.py --dry    # 只看看会裁成什么样
```

末尾会自动加 40ms 淡出、开头加 5ms 淡入，不会爆音。同名的话 `.wav` 优先级高于 `.mp3`，原文件会被复制进 `custom/_orig/` 留底。

> `.wav` 走系统播放通道，**同一时刻只响一个**——长音效被后来的短音效打断是正常的。想叠加就把那一条改回 `.mp3`（走 Qt 播放器，可重叠）。

## 调手感

`config.py` 里改：

- `PET_H` 桌宠高度（默认 240）
- `GRAVITY` / `GROUND_BOUNCE` 掉下去有多猛、弹几下
- `WALK_SPEED` / `IDLE_MIN` / `WALK_MAX` 多久动一次、走多快
- `SATIETY_DECAY` 饿得多快
- `MAX_ROT` 身体最多倾斜几度
- `LINES` 所有台词

改表情或字体的手感在 `ui/bubble.py`；想让它别盖住任务栏图标，调 `_bounds()` 里的 `availableGeometry`。
