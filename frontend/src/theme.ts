import type { ThemeConfig } from 'antd'

/**
 * 全站设计令牌（2026-10-18 改版）。
 * 取值与 styles.css 的 :root 一一对应，改一处要同步另一处。
 * 版式与材质来自星巴克公开设计语言：暖纸画布、四阶品牌绿、12px 卡片圆角、
 * 胶囊按钮、极轻阴影；金色只承担「待人判定」这一种语义。
 */
export const palette = {
  background: '#F2F0EB',
  backgroundDeep: '#EDEBE9',
  surface: '#FFFFFF',
  surfaceWarm: '#FBF9F5',
  surfaceGold: '#FAF6EE',
  ink: '#1C2B26',
  inkMuted: '#5D6C64',
  inkFaint: '#8B958E',
  brand: '#006241',
  brandDark: '#004D34',
  brandAccent: '#00754A',
  brandHouse: '#1E3932',
  brandPale: '#D4E9E2',
  gold: '#CBA258',
  goldSoft: '#DFC49D',
  supported: '#1B6A55',
  review: '#8A6414',
  danger: '#C82014',
  rule: '#E2DCD2',
  ruleSoft: '#EFEAE2',
  subtle: '#F4F1EB',
} as const

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: palette.brandAccent,
    colorLink: palette.brand,
    colorInfo: palette.brand,
    colorSuccess: palette.supported,
    colorWarning: palette.gold,
    colorError: palette.danger,
    colorText: palette.ink,
    colorTextSecondary: palette.inkMuted,
    colorBorder: palette.rule,
    colorBorderSecondary: palette.ruleSoft,
    colorBgBase: palette.background,
    colorBgLayout: palette.background,
    colorBgContainer: palette.surface,
    borderRadius: 4,
    borderRadiusLG: 12,
    fontSize: 14,
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif',
    boxShadowSecondary: '0 0 .5px rgba(30,57,50,.16), 0 1px 2px rgba(30,57,50,.08)',
  },
  components: {
    Layout: {
      headerBg: palette.surface,
      siderBg: palette.brandHouse,
      bodyBg: palette.background,
    },
    Menu: {
      itemSelectedBg: palette.surface,
      itemSelectedColor: palette.brandHouse,
      itemBorderRadius: 50,
    },
    Card: {
      borderRadiusLG: 12,
      headerBg: palette.surfaceWarm,
    },
    Button: {
      // 胶囊按钮是这套版式的标志动作
      borderRadius: 50,
      borderRadiusLG: 50,
      borderRadiusSM: 50,
      primaryShadow: 'none',
      defaultShadow: 'none',
    },
    Input: {
      borderRadius: 4,
      activeBorderColor: palette.brandAccent,
      hoverBorderColor: palette.gold,
    },
    InputNumber: {
      borderRadius: 4,
    },
    Select: {
      borderRadius: 4,
    },
    Drawer: {
      colorBgElevated: palette.surface,
    },
    Table: {
      headerBg: palette.surfaceWarm,
      borderColor: palette.ruleSoft,
    },
    Tag: {
      borderRadiusSM: 50,
    },
    Modal: {
      borderRadiusLG: 12,
    },
  },
}
