import type { ThemeConfig } from 'antd'

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#b21f2d',
    colorInfo: '#31586f',
    colorSuccess: '#2f6b53',
    colorWarning: '#a05a1b',
    colorError: '#b21f2d',
    colorText: '#20201e',
    colorTextSecondary: '#686761',
    colorBorder: '#d8d4ca',
    colorBorderSecondary: '#e6e2d9',
    colorBgBase: '#f6f3ec',
    colorBgLayout: '#f6f3ec',
    colorBgContainer: '#fbfaf6',
    borderRadius: 2,
    borderRadiusLG: 2,
    fontSize: 14,
    fontFamily: 'Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    boxShadowSecondary: 'none',
  },
  components: {
    Layout: {
      headerBg: '#f6f3ec',
      siderBg: '#f6f3ec',
      bodyBg: '#f6f3ec',
    },
    Menu: {
      itemSelectedBg: '#eee8de',
      itemSelectedColor: '#8f1824',
      itemBorderRadius: 0,
    },
    Card: {
      borderRadiusLG: 2,
      headerBg: '#fbfaf6',
    },
    Button: {
      borderRadius: 2,
      primaryShadow: 'none',
    },
    Input: {
      borderRadius: 2,
    },
    Select: {
      borderRadius: 2,
    },
  },
}
