import type { ThemeConfig } from 'antd'

export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#4f46e5',
    colorInfo: '#4f46e5',
    borderRadius: 10,
    colorBgLayout: '#f6f7fb',
    fontSize: 14,
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      siderBg: '#ffffff',
      bodyBg: '#f6f7fb',
    },
    Menu: {
      itemSelectedBg: '#eef0ff',
      itemSelectedColor: '#4f46e5',
      itemBorderRadius: 8,
    },
    Card: {
      borderRadiusLG: 12,
    },
  },
}
