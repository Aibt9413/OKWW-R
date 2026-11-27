from ok import TriggerTask, Logger
from src.scene.WWScene import WWScene
from src.task.BaseWWTask import BaseWWTask

logger = Logger.get_logger(__name__)


class AutoLoginTask(BaseWWTask, TriggerTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 5
        self.name = "🔑 Auto Login"
        self.description = "Auto Login After Game Starts"

    def run(self):
        if self.logged_in:
            pass
        elif self.scene.in_team(self.in_team_and_world):
            self.logged_in = True
            self.op_log("检测到已登录")
        else:
            # 这个触发器每 5 秒跑一次 —— 提示只记一次，登录成功后才会重新允许
            self.op_log_login_once("正在登录游戏...")
            return self.wait_login()
