#include "stm32f1xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include <stdbool.h>

/* ĐỊNH NGHĨA CHÂN NGOẠI VI */
#define MQ2_AO_PIN        GPIO_PIN_0   // PA0 (ADC1_IN0) - Biến trở Gas
#define MQ2_DO_PIN        GPIO_PIN_1   // PA1 - Nút bấm Cảnh báo Gas
#define FLAME_DO_PIN      GPIO_PIN_2   // PA2 - Nút bấm Cảnh báo Lửa

#define RELAY_FAN_PIN     GPIO_PIN_0   // PB0 - Quạt hút
#define BUZZER_PIN        GPIO_PIN_1   // PB1 - Còi báo động
#define LED_GREEN_PIN     GPIO_PIN_12  // PB12 - Đèn SAFE (An toàn)
#define LED_RED_PIN       GPIO_PIN_13  // PB13 - Đèn ALARM (Báo động)

ADC_HandleTypeDef hadc1;

/* NỐI HÀM NGẮT FREERTOS VỚI STM32 HAL (CHỐNG TREO VI XỬ LÝ) */
extern void vPortSVCHandler(void);
extern void xPortPendSVHandler(void);
extern void xPortSysTickHandler(void);

void SVC_Handler(void) { vPortSVCHandler(); }
void PendSV_Handler(void) { xPortPendSVHandler(); }
void SysTick_Handler(void) {
    HAL_IncTick();
    if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED) {
        xPortSysTickHandler();
    }
}

void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_ADC1_Init(void);

/* TASK FREERTOS: GIÁM SÁT CẢM BIẾN & ĐIỀU KHIỂN HỆ THỐNG */
void Task_MonitorAndControl(void *pvParameters) {
    (void)pvParameters;

    for (;;) {
        // 1. Đọc trạng thái 2 nút nhấn (Được kéo lên VCC, bấm nút = GPIO_PIN_RESET)
        GPIO_PinState gas_do = HAL_GPIO_ReadPin(GPIOA, MQ2_DO_PIN);
        GPIO_PinState flame_do = HAL_GPIO_ReadPin(GPIOA, FLAME_DO_PIN);

        // 2. Đọc giá trị ADC Biến trở Gas (PA0)
        uint32_t adc_val = 0;
        HAL_ADC_Start(&hadc1);
        if (HAL_ADC_PollForConversion(&hadc1, 1) == HAL_OK) {
            adc_val = HAL_ADC_GetValue(&hadc1);
        }
        HAL_ADC_Stop(&hadc1);

        uint16_t gas_ppm = (uint16_t)((adc_val * 1000) / 4095);

        // 3. Kiểm tra điều kiện Cảnh báo
        bool is_alarm = (gas_ppm >= 400) || (gas_do == GPIO_PIN_RESET) || (flame_do == GPIO_PIN_RESET);

        if (is_alarm) {
            // TRẠNG THÁI BÁO ĐỘNG
            HAL_GPIO_WritePin(GPIOB, LED_GREEN_PIN, GPIO_PIN_RESET); // Tắt LED Xanh
            HAL_GPIO_WritePin(GPIOB, LED_RED_PIN, GPIO_PIN_SET);     // Bật LED Đỏ
            HAL_GPIO_WritePin(GPIOB, RELAY_FAN_PIN, GPIO_PIN_SET);   // Bật Quạt
            HAL_GPIO_WritePin(GPIOB, BUZZER_PIN, GPIO_PIN_SET);      // Bật Còi
        } else {
            // TRẠNG THÁI AN TOÀN
            HAL_GPIO_WritePin(GPIOB, LED_GREEN_PIN, GPIO_PIN_SET);   // Bật LED Xanh
            HAL_GPIO_WritePin(GPIOB, LED_RED_PIN, GPIO_PIN_RESET);   // Tắt LED Đỏ
            HAL_GPIO_WritePin(GPIOB, RELAY_FAN_PIN, GPIO_PIN_RESET); // Tắt Quạt
            HAL_GPIO_WritePin(GPIOB, BUZZER_PIN, GPIO_PIN_RESET);   // Tắt Còi
        }

        vTaskDelay(pdMS_TO_TICKS(50)); // Chu kỳ quét 50ms
    }
}

int main(void) {
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_ADC1_Init();

    // Bật sẵn LED Xanh ngay khi cấp nguồn
    HAL_GPIO_WritePin(GPIOB, LED_GREEN_PIN, GPIO_PIN_SET);

    // Khởi tạo Task FreeRTOS
    xTaskCreate(Task_MonitorAndControl, "MonitorTask", 256, NULL, 2, NULL);

    // Chạy FreeRTOS Scheduler
    vTaskStartScheduler();

    while (1) {}
}

void SystemClock_Config(void) {
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    RCC_OscInitStruct.HSIState = RCC_HSI_ON;
    RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    HAL_RCC_OscConfig(&RCC_OscInitStruct);

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                                |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

    HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0);
}

static void MX_GPIO_Init(void) {
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    // Cấu hình Output: Relay (PB0), Buzzer (PB1), LED Xanh (PB12), LED Đỏ (PB13)
    GPIO_InitStruct.Pin = RELAY_FAN_PIN | BUZZER_PIN | LED_GREEN_PIN | LED_RED_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    // Cấu hình Input: Gas DO (PA1), Flame DO (PA2) với điện trở kéo lên Pull-up
    GPIO_InitStruct.Pin = MQ2_DO_PIN | FLAME_DO_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}

static void MX_ADC1_Init(void) {
    ADC_ChannelConfTypeDef sConfig = {0};

    __HAL_RCC_ADC1_CLK_ENABLE();
    hadc1.Instance = ADC1;
    hadc1.Init.ScanConvMode = ADC_SCAN_DISABLE;
    hadc1.Init.ContinuousConvMode = DISABLE;
    hadc1.Init.DataAlign = ADC_DATAALIGN_RIGHT;
    hadc1.Init.NbrOfConversion = 1;
    HAL_ADC_Init(&hadc1);

    sConfig.Channel = ADC_CHANNEL_0;
    sConfig.Rank = ADC_REGULAR_RANK_1;
    sConfig.SamplingTime = ADC_SAMPLETIME_1CYCLE_5;
    HAL_ADC_ConfigChannel(&hadc1, &sConfig);
}