#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度百科药品信息爬虫

功能:
1. 从百度百科抓取药品详细信息
2. 解析药品适应症、用法用量、注意事项等
3. 将数据存入PostgreSQL数据库
"""

import requests
from bs4 import BeautifulSoup
import time
import random
import psycopg2
from urllib.parse import quote
import os
import sys
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


class BaiduBaikeCrawler:
    """百度百科爬虫"""

    def __init__(self):
        self.base_url = "https://baike.baidu.com/item/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        }
        self.session = requests.Session()
        self.delay_min = 2
        self.delay_max = 5

        # 数据库连接
        self.db_conn = None
        self.connect_db()

    def connect_db(self):
        """连接数据库"""
        try:
            self.db_conn = psycopg2.connect(
                host=os.getenv('DATABASE_HOST', 'localhost'),
                port=os.getenv('DATABASE_PORT', 5432),
                database=os.getenv('DATABASE_NAME', 'medical_assistant'),
                user=os.getenv('DATABASE_USER', 'user'),
                password=os.getenv('DATABASE_PASSWORD', 'password')
            )
            print("✓ 数据库连接成功")
        except Exception as e:
            print(f"✗ 数据库连接失败: {e}")
            sys.exit(1)

    def fetch_page(self, drug_name):
        """获取药品百科页面"""
        try:
            url = self.base_url + quote(drug_name)
            print(f"正在获取: {url}")

            response = self.session.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'

            return response.text
        except requests.RequestException as e:
            print(f"✗ 获取页面失败 {drug_name}: {e}")
            return None

    def parse_drug_info(self, html, drug_name):
        """解析药品信息"""
        if not html:
            return None

        soup = BeautifulSoup(html, 'lxml')

        drug_info = {
            'generic_name': drug_name,
            'brand_names': [],
            'active_ingredients': [],
            'indications': '',
            'dosage': '',
            'side_effects': '',
            'contraindications': '',
            'warnings': '',
            'storage': '',
        }

        try:
            # 查找基本信息框
            info_box = soup.find('div', class_='basic-info')
            if info_box:
                # 提取商品名
                for item in info_box.find_all('dt'):
                    if '商品名' in item.text or '别名' in item.text:
                        dd = item.find_next_sibling('dd')
                        if dd:
                            names = dd.get_text(strip=True).replace('、', ',').split(',')
                            drug_info['brand_names'] = [n.strip() for n in names if n.strip()]

            # 查找正文段落
            content = soup.find('div', class_='lemma-summary') or soup.find('div', class_='para')
            if content:
                paragraphs = content.find_all(['div', 'p'], class_='para')

                for para in paragraphs:
                    text = para.get_text(strip=True)

                    # 适应症
                    if any(keyword in text for keyword in ['适应症', '用于', '适用于', '主治']):
                        drug_info['indications'] = text[:500]

                    # 用法用量
                    if any(keyword in text for keyword in ['用法用量', '用法', '用量', '服用方法']):
                        drug_info['dosage'] = text[:500]

                    # 不良反应
                    if any(keyword in text for keyword in ['不良反应', '副作用', '常见不良']):
                        drug_info['side_effects'] = text[:500]

                    # 禁忌
                    if any(keyword in text for keyword in ['禁忌', '禁用']):
                        drug_info['contraindications'] = text[:500]

                    # 注意事项
                    if any(keyword in text for keyword in ['注意事项', '警告', '慎用']):
                        drug_info['warnings'] = text[:500]

                    # 储存
                    if any(keyword in text for keyword in ['贮藏', '储存', '保存']):
                        drug_info['storage'] = text[:200]

            # 如果主要信息为空,尝试从其他区域提取
            if not drug_info['indications']:
                # 尝试查找标题包含"适应症"的段落
                for heading in soup.find_all(['h2', 'h3']):
                    if '适应症' in heading.get_text():
                        next_para = heading.find_next('div', class_='para')
                        if next_para:
                            drug_info['indications'] = next_para.get_text(strip=True)[:500]
                            break

            return drug_info

        except Exception as e:
            print(f"✗ 解析失败 {drug_name}: {e}")
            return None

    def save_to_db(self, drug_info):
        """保存药品信息到数据库"""
        if not drug_info:
            return False

        try:
            cursor = self.db_conn.cursor()

            # 生成drug_id
            drug_id = f"crawled_{drug_info['generic_name'].replace(' ', '_')}"

            # 检查是否已存在
            cursor.execute(
                "SELECT drug_id FROM drugs WHERE generic_name = %s",
                (drug_info['generic_name'],)
            )

            if cursor.fetchone():
                print(f"  药品已存在,跳过: {drug_info['generic_name']}")
                return True

            # 插入数据
            insert_query = """
                INSERT INTO drugs (
                    drug_id, generic_name, brand_names, active_ingredients,
                    is_otc, indications, dosage, side_effects,
                    contraindications, warnings, storage, source
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'crawler'
                )
            """

            cursor.execute(insert_query, (
                drug_id,
                drug_info['generic_name'],
                drug_info['brand_names'],
                drug_info['active_ingredients'],
                True,  # 默认为OTC
                drug_info['indications'] or None,
                drug_info['dosage'] or None,
                drug_info['side_effects'] or None,
                drug_info['contraindications'] or None,
                drug_info['warnings'] or None,
                drug_info['storage'] or None
            ))

            self.db_conn.commit()
            print(f"✓ 保存成功: {drug_info['generic_name']}")
            return True

        except Exception as e:
            print(f"✗ 保存失败 {drug_info['generic_name']}: {e}")
            self.db_conn.rollback()
            return False

    def crawl_drug(self, drug_name):
        """爬取单个药品信息"""
        print(f"\n{'='*60}")
        print(f"开始爬取: {drug_name}")
        print('='*60)

        # 获取页面
        html = self.fetch_page(drug_name)
        if not html:
            return False

        # 解析信息
        drug_info = self.parse_drug_info(html, drug_name)
        if not drug_info:
            return False

        # 保存到数据库
        success = self.save_to_db(drug_info)

        # 随机延迟
        delay = random.uniform(self.delay_min, self.delay_max)
        print(f"等待 {delay:.1f} 秒...")
        time.sleep(delay)

        return success

    def crawl_from_file(self, file_path):
        """从文件读取药品列表并爬取"""
        if not os.path.exists(file_path):
            print(f"✗ 文件不存在: {file_path}")
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            drug_names = [line.strip() for line in f if line.strip()]

        print(f"共有 {len(drug_names)} 个药品待爬取")

        success_count = 0
        fail_count = 0

        for i, drug_name in enumerate(drug_names, 1):
            print(f"\n进度: {i}/{len(drug_names)}")

            if self.crawl_drug(drug_name):
                success_count += 1
            else:
                fail_count += 1

        print(f"\n{'='*60}")
        print(f"爬取完成!")
        print(f"成功: {success_count}")
        print(f"失败: {fail_count}")
        print('='*60)

    def close(self):
        """关闭连接"""
        if self.db_conn:
            self.db_conn.close()
            print("\n数据库连接已关闭")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='百度百科药品信息爬虫')
    parser.add_argument(
        '-f', '--file',
        default='drug_list.txt',
        help='药品列表文件路径 (默认: drug_list.txt)'
    )
    parser.add_argument(
        '-d', '--drug',
        help='单个药品名称'
    )

    args = parser.parse_args()

    crawler = BaiduBaikeCrawler()

    try:
        if args.drug:
            # 爬取单个药品
            crawler.crawl_drug(args.drug)
        else:
            # 从文件爬取
            crawler.crawl_from_file(args.file)
    except KeyboardInterrupt:
        print("\n\n用户中断")
    finally:
        crawler.close()


if __name__ == '__main__':
    main()
