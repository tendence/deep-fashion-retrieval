# -*- coding: utf-8 -*-
from __future__ import print_function

import torch
import random
import torch.nn as nn
import torch.optim as optim
from torchvision import transforms
from torch.autograd import Variable
from myconfig import cfg
from utils import dump_model
from data import Fashion_attr_prediction, Fashion_inshop
from net import f_model


data_transform_train = transforms.Compose([
    transforms.Scale(cfg.IMG_SIZE),
    transforms.RandomSizedCrop(cfg.CROP_SIZE),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])

data_transform_test = transforms.Compose([
    transforms.Scale(cfg.CROP_SIZE),
    transforms.CenterCrop(cfg.CROP_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])


train_loader = torch.utils.data.DataLoader(
    Fashion_attr_prediction(type="train", transform=data_transform_train),
    batch_size=cfg.TRAIN_BATCH_SIZE, num_workers=cfg.NUM_WORKERS, pin_memory=True
)

test_loader = torch.utils.data.DataLoader(
    Fashion_attr_prediction(type="test", transform=data_transform_test),
    batch_size=cfg.TEST_BATCH_SIZE, num_workers=cfg.NUM_WORKERS, pin_memory=True
)

triplet_loader = torch.utils.data.DataLoader(
    Fashion_attr_prediction(type="triplet", transform=data_transform_train),
    batch_size=cfg.TRIPLET_BATCH_SIZE, num_workers=cfg.NUM_WORKERS, pin_memory=True
)

if cfg.ENABLE_INSHOP_DATASET:
    triplet_in_shop_loader = torch.utils.data.DataLoader(
        Fashion_inshop(type="train", transform=data_transform_train),
        batch_size=cfg.TRIPLET_BATCH_SIZE, num_workers=cfg.NUM_WORKERS, pin_memory=True
    )

model = f_model(freeze_param=cfg.FREEZE_PARAM, model_path=cfg.DUMPED_MODEL).cuda(cfg.GPU_ID)
optimizer = optim.SGD(filter(lambda p: p.requires_grad, model.parameters()), lr=cfg.LR, momentum=cfg.MOMENTUM)


def train(epoch):
    model.train()
    criterion_c = nn.CrossEntropyLoss()
    if cfg.ENABLE_TRIPLET_WITH_COSINE:
        criterion_t = cfg.TripletMarginLossCosine()
    else:
        criterion_t = nn.TripletMarginLoss()
    triplet_loader_iter = iter(triplet_loader)
    triplet_type = 0
    if cfg.ENABLE_INSHOP_DATASET:
        triplet_in_shop_loader_iter = iter(triplet_in_shop_loader)
    for batch_idx, (data, target) in enumerate(train_loader):
        if batch_idx % cfg.TEST_INTERVAL == 0:
            test()
        data, target = data.cuda(cfg.GPU_ID), target.cuda(cfg.GPU_ID)
        data, target = Variable(data), Variable(target)
        optimizer.zero_grad()
        outputs = model(data)[0]
        classification_loss = criterion_c(outputs, target)
        if cfg.TRIPLET_WEIGHT:
            if cfg.ENABLE_INSHOP_DATASET and random.random() < cfg.INSHOP_DATASET_PRECENT:
                triplet_type = 1
                try:
                    data_tri_list = next(triplet_in_shop_loader_iter)
                except StopIteration:
                    triplet_in_shop_loader_iter = iter(triplet_in_shop_loader)
                    data_tri_list = next(triplet_in_shop_loader_iter)
            else:
                triplet_type = 0
                try:
                    data_tri_list = next(triplet_loader_iter)
                except StopIteration:
                    triplet_loader_iter = iter(triplet_loader)
                    data_tri_list = next(triplet_loader_iter)
            triplet_batch_size = data_tri_list[0].shape[0]
            data_tri = torch.cat(data_tri_list, 0)
            data_tri = data_tri.cuda(cfg.GPU_ID)
            data_tri = Variable(data_tri, requires_grad=True)
            feats = model(data_tri)[1]
            triplet_loss = criterion_t(
                feats[:triplet_batch_size],
                feats[triplet_batch_size:2 * triplet_batch_size],
                feats[2 * triplet_batch_size:]
            )
            loss = classification_loss + triplet_loss * cfg.TRIPLET_WEIGHT
        else:
            loss = classification_loss
        loss.backward()
        optimizer.step()
        if batch_idx % cfg.LOG_INTERVAL == 0:
            if cfg.TRIPLET_WEIGHT:
                print('Train Epoch: {} [{}/{} ({:.0f}%)]\tAll Loss: {:.4f}\t'
                      'Triple Loss({}): {:.4f}\tClassification Loss: {:.4f}'.format(
                    epoch, batch_idx * len(data), len(train_loader.dataset),
                    100. * batch_idx / len(train_loader), loss.data[0], triplet_type,
                    triplet_loss.data[0], classification_loss.data[0]))
            else:
                print('Train Epoch: {} [{}/{} ({:.0f}%)]\tClassification Loss: {:.4f}'.format(
                    epoch, batch_idx * len(data), len(train_loader.dataset),
                           100. * batch_idx / len(train_loader), loss.data[0]))
        if batch_idx and batch_idx % cfg.DUMP_INTERVAL == 0:
            print('Model saved to {}'.format(dump_model(model, epoch, batch_idx)))

    print('Model saved to {}'.format(dump_model(model, epoch)))


def test():
    model.eval()
    criterion = nn.CrossEntropyLoss(size_average=False)
    test_loss = 0
    correct = 0
    for batch_idx, (data, target) in enumerate(test_loader):
        data, target = data.cuda(cfg.GPU_ID), target.cuda(cfg.GPU_ID)
        data, target = Variable(data, volatile=True), Variable(target)
        output = model(data)[0]
        test_loss += criterion(output, target).data[0]
        pred = output.data.max(1, keepdim=True)[1]
        correct += pred.eq(target.data.view_as(pred)).cpu().sum()
        if batch_idx > cfg.TEST_BATCH_COUNT:
            break
    test_loss /= (cfg.TEST_BATCH_COUNT * cfg.TEST_BATCH_SIZE)
    print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(
        float(test_loss), correct, (cfg.TEST_BATCH_COUNT * cfg.TEST_BATCH_SIZE),
        float(100. * correct / (cfg.TEST_BATCH_COUNT * cfg.TEST_BATCH_SIZE))))


if __name__ == "__main__":
    for epoch in range(1, cfg.EPOCH + 1):
        train(epoch)
