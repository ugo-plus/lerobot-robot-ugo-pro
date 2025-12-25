# AIロボット向け模倣学習キット (ugo Pro R&Dモデル) - 操作マニュアル

## 概要

ここでは、ugo Pro R&Dモデルの模倣学習キットで、データ収集から学習までを行うための手順をご紹介します。

開発 PC 側で LeRobot をセットアップし、ugo Controller MCU と有線 LAN で接続して teleoperate -> record -> dataset viz -> replay -> train の流れで進めます。

## 必要なもの

- ugo Pro R&Dモデル
- 有線LANケーブルおよびUSBカメラを３つ接続できるPC
- バイラテラルコントローラ

## 1. 環境構築: conda のインストール

パッケージ管理ソフトウェア `Conda` をインストールし、専用の Python 環境を作成します。Python 3.10+ を推奨します。

[Download the conda-forge Installer](https://conda-forge.org/download/)

インストーラの手順に従ってCondaをインストールし、ターミナルにて `conda create` で新たな環境を構築します。

```bash
conda create -n lerobot python=3.10
```

`Conda` で一度環境を構築済みの場合は、以下の `conda activate` コマンドで、いつでも環境を復元できます。

```bash
conda activate lerobot
```

## 2. LeRobot のインストール

公式ドキュメントに従って LeRobot をインストールします。GPU を使う場合は CUDA 対応もここで済ませます。

```bash
pip install lerobot
```

[LeRobot Installation Document](https://huggingface.co/docs/lerobot/installation)


## 3. LeRobot - ugo Pro プラグインの導入

```bash
pip install lerobot-robot-ugo-pro
```

## 4. カメラの設定確認

ugo Pro R&Dモデルに搭載されている３つのカメラ（頭部／右手／左手）の情報を確認します。LeRobotのコマンドを利用して、接続済みのカメラ一覧を確認し、デバイスID/解像度/FPSを把握します。

```bash
lerobot-find-cameras

--- Detected Cameras ---
Camera #0:
  Name: OpenCV Camera @ 0
  Id: 0
  Default stream profile:
    Width: 1920
    Height: 1080
    Fps: 15.000015
--------------------
Camera #1:
  Name: OpenCV Camera @ 1
  Id: 1
  Default stream profile:
    Width: 1920
    Height: 1080
    Fps: 15.000015
--------------------
Camera #2:
  Name: OpenCV Camera @ 2
  Id: 2
  Default stream profile:
    Width: 1920
    Height: 1080
    Fps: 15.000015
...

```

各カメラのIDを `front/right/left` それぞれの `index_or_path` 設定に反映して、今後のlerobotコマンドのパラメータ `--robot.cameras="{...}"` に付与してください。

```json
{
  front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 15}, 
  right: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}, 
  left: {type: opencv, index_or_path: 2, width: 1920, height: 1080, fps: 15}
}
```

## 5. データ取得 PC と ugo Controller MCU との LAN 接続の確認

MCU と同じサブネットで通信できることを確認します。
必要に応じて `--robot.telemetry_host` / `--robot.command_port` 等を設定します。

## 6. データ取得の確認

Teleop でストリームを確認します。カメラ設定は環境に合わせて更新してください。

```bash
lerobot-teleoperate \
  --robot.type=ugo_pro \
  --robot.id=my_ugo_pro \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 15}, right: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}, left: {type: opencv, index_or_path: 2, width: 1920, height: 1080, fps: 15}}" \
  --teleop.type=ugo_bilcon \
  --teleop.id=my_ugo_bilcon \
  --display_data=true
```

## 7. レコーディング

データセットの出力先とエピソード数を指定します。

```bash
lerobot-record \
  --robot.type=ugo_pro \
  --robot.id=my_ugo_pro \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 15}, right: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 15}, left: {type: opencv, index_or_path: 2, width: 1920, height: 1080, fps: 15}}" \
  --teleop.type=ugo_bilcon \
  --teleop.id=my_ugo_bilcon \
  --dataset.num_episodes=10 \
  --dataset.fps=15 \
  --dataset.repo_id=your-name/ugo_pro_demo \
  --dataset.single_task="Pick and place"
```

一度、レコーディングした後に、同じ `dataset.repo_id` で再度レコーディングをしようとすると、以下のようなエラーが発生します。

```Error
FileExistsError: [Errno 17] File exists: '~/.cache/huggingface/lerobot/your-name/ugo_pro_demo'
```

その場合は、同ディレクトリを削除してください。
```
rm -fr ~/.cache/huggingface/lerobot/your-name/ugo_pro_demo
```

## 8. データセットの確認

```bash
lerobot-dataset-viz \
  --repo-id=your-name/ugo_pro_demo \
  --episode-index=0
```

## 9. リプレイ

```bash
lerobot-replay \
  --robot.type=ugo_pro \
  --robot.id=my_ugo_pro \
  --dataset.repo_id=your-name/ugo_pro_demo \
  --dataset.episode=0
```

## 10.  学習: ACT Policy の例

学習用の出力先とポリシー設定を指定します。

```bash
lerobot-train \
  --dataset.repo_id=your-name/ugo_pro_demo \
  --policy.type=act \
  --output_dir=outputs/train/act-demo \
  --job_name=act-demo \
  --policy.device=cuda
```
