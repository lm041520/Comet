import type { ThemeConfig } from 'antd'

// 参考 MemoryBear 设计语言：近黑主色 + 蓝色强调 + 柔和阴影 + 中性灰
export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#155EEF',
    colorInfo: '#155EEF',
    colorSuccess: '#369F21',
    colorError: '#FF5D34',
    colorTextBase: '#171719',
    colorBgLayout: '#FAFAFA',
    borderRadius: 8,
    fontSize: 16,
    fontFamily:
      "'PingFang SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Microsoft YaHei', sans-serif",
    boxShadowSecondary:
      '0px 4px 6px -2px rgba(16, 24, 40, 0.03), 0px 12px 16px -4px rgba(16, 24, 40, 0.08)',
  },
  components: {
    Layout: {
      siderBg: '#ffffff',
      headerBg: '#ffffff',
      headerHeight: 64,
      bodyBg: '#FAFAFA',
    },
    Menu: {
      itemBg: '#ffffff',
      itemSelectedBg: '#EEF4FF',
      itemSelectedColor: '#155EEF',
      itemHoverBg: '#F7F7F7',
      itemColor: '#475467',
      itemHeight: 48,
      itemMarginInline: 8,
      fontSize: 16,
    },
    Card: {
      borderRadiusLG: 12,
    },
    Button: {
      controlHeight: 40,
      fontWeight: 500,
    },
  },
}
