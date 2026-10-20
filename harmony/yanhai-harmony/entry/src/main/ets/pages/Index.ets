import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';

/** 产品的公网地址。
 *
 *  换成自己部署的地址时只改这一行；结尾要有斜杠——
 *  界面里的接口前缀是相对路径（`/AgentDemo/start/api`），少了斜杠会 404。
 *  真机连局域网 http 时，HarmonyOS 默认拦明文流量，需要在 DevEco 里配
 *  network_config 打开 cleartextTraffic，见 docs/协作与运维/鸿蒙手机端.md。
 */
const APP_URL: string = 'https://snowsong.top/AgentDemo/start/';

const TAG: string = 'Yanhai';

@Entry
@Component
struct Index {
  private controller: webview.WebviewController = new webview.WebviewController();
  @State progress: number = 0;
  @State failed: boolean = false;
  @State failReason: string = '';

  /** 系统返回键：网页里还能后退就先退网页，退到头再退应用。 */
  onBackPress(): boolean {
    if (this.controller.accessBackward()) {
      this.controller.backward();
      return true;
    }
    return false;
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Web({ src: APP_URL, controller: this.controller })
        .domStorageAccess(true)
        .javaScriptAccess(true)
        .fileAccess(false)
        .zoomAccess(false)
        .horizontalScrollBarAccess(false)
        .darkMode(WebDarkMode.Off)
        .forceDarkAccess(false)
        .onProgressChange((event) => {
          this.progress = event.newProgress;
        })
        .onPageEnd(() => {
          this.progress = 100;
        })
        .onErrorReceive((event) => {
          if (event && event.error) {
            this.failed = true;
            this.failReason = `${event.error.errorCode}: ${event.error.errorInfo}`;
            hilog.error(0x0000, TAG, 'web error %{public}s', this.failReason);
          }
        })

      if (this.progress < 100 && !this.failed) {
        Column({ space: 12 }) {
          LoadingProgress().width(48).height(48).color('#006241');
          Text('正在连接研海寻踪').fontSize(13).fontColor('#6B655D');
        }
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#F2F0EB')
        .width('100%')
        .height('100%')
      }

      if (this.failed) {
        Column({ space: 16 }) {
          Text('连不上研海寻踪').fontSize(18).fontColor('#1E3932');
          Text(this.failReason)
            .fontSize(12)
            .fontColor('#6B655D')
            .textAlign(TextAlign.Center)
            .padding({ left: 32, right: 32 });
          Button('重试')
            .backgroundColor('#006241')
            .fontColor('#FFFFFF')
            .onClick(() => {
              this.failed = false;
              this.progress = 0;
              this.controller.loadUrl(APP_URL);
            })
        }
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#F2F0EB')
        .width('100%')
        .height('100%')
      }
    }
    .width('100%')
    .height('100%')
  }
}
