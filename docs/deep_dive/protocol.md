### Text Protocol Deep Dive

#### Commands
- LOGIN|user|password → OK|WELCOME / ERR|AUTH
- LIST → BEGIN..END 文件清单
- UPLOAD|filename|size|sha256hex → READY → [bytes] → OK|<sha>
- DOWNLOAD|filename → SIZE|size|sha
- SUB|room[|since_id] / UNSUB|room
- HISTORY|room|limit[|since_id]
- PUBT|room|len|sha → READY → [bytes] → OK|PUBT|<event_id>
- PUBF|room|filename|size|sha → READY → [bytes] → OK|PUBF|<event_id>

Why：文本协议便于学习与调试（可用 netcat 手工交互），最大化教学价值。

#### Events
- EVT|TEXT|room|ts|user|event_id|len|sha\n + payload
- EVT|FILE|room|ts|user|event_id|filename|size|sha\n

一致性：TEXT 的 payload 也被落地在 `texts/<eid>.txt`，确保 HISTORY 回放准确无丢失。

#### Errors
- ERR|FORMAT|... / ERR|PERM|... / ERR|CHECKSUM|... / ERR|BUSY|...

语义清晰、可脚本断言，便于自动化测试与问题定位。


