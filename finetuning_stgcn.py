from __future__ import print_function
from __future__ import division
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import torchvision
import torch.utils.data as data
from torchvision import datasets, models, transforms
import matplotlib.pyplot as plt
import time
import os
import sys
import copy
import json
import numpy as np

from net.st_gcn import Model
from myDataset import Dataset

def save_checkpoint(epoch, model, optimizer, scheduler, path):
    state = {
        'epoch': epoch,
        'model': model.state_dict(),
        'optimizer': optimizer.state_dict(),
        'scheduler': scheduler.state_dict()
    }
    torch.save(state, path)

for cluster in ['basic', 'alerting', 'daily_life']:
    for nframes in [32]:
        root_dir = 'Dataset/aggregorio_skeletons_numpy/{}'.format(cluster)
        dist_dir = 'stats/{}/testing'.format(cluster, nframes)

        checkpoint_path = dist_dir+"/checkpoint"
        if not os.path.exists(dist_dir):
            os.makedirs(dist_dir)
            os.makedirs(checkpoint_path)

        best_model_path = dist_dir+"/best_model.pt"
        readme_path = dist_dir+"/readme.txt"
        stats_path = dist_dir+"/stats.txt"
        confusion_matrix_path = dist_dir+"/confusion_matrix.txt"
        plot_path = dist_dir+"/plot.png"

        batch_size = 256
        num_epochs = 50

        dataset_train_path = root_dir+'/train'
        dataset_train = Dataset(dataset_train_path, nframes, campionamento=3)
        loader_train = data.DataLoader(
                                dataset_train,
                                batch_size=batch_size,
                            	shuffle=True,
                            	pin_memory=True,
                                num_workers = 4
                            )

        dataset_test_path = root_dir+'/test'
        dataset_test = Dataset(dataset_test_path, nframes, campionamento=3)
        loader_test = data.DataLoader(
                                dataset_test,
                                batch_size=batch_size,
                            	shuffle=False,
                            	pin_memory=True,
                                num_workers = 4
                            )

        num_classes = len(dataset_train.classes)

        print('loading model')
        model_args = {
          'in_channels': 3,
          'num_class': 400,
          'edge_importance_weighting': True,
          'graph_args': {
            'layout': 'openpose',
            'strategy': 'spatial'
          }
        }
        model_weight = 'models/st_gcn.kinetics.pt'
        model = Model(model_args['in_channels'], model_args['num_class'],
                        model_args['graph_args'], model_args['edge_importance_weighting'])
        model.load_state_dict(torch.load(model_weight))


        for param in model.parameters():
            param.requires_grad = False

        model.fcn = nn.Conv2d(256, num_classes, kernel_size=(1, 1), stride=(1, 1))

        # Send the model to GPU
        model.cuda()

        print("parameters to learn:")
        params_to_update = []
        params_to_update_name = []
        for name,param in model.named_parameters():
            if param.requires_grad == True:
                params_to_update.append(param)
                params_to_update_name.append(name)
                print("\t",name)

        # Observe that all parameters are being optimized
        w_decay = 0.01
        optimizer = optim.SGD(params_to_update, lr=0.1, momentum=0.9, weight_decay=w_decay)
        criterion = nn.CrossEntropyLoss()

        scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, [25,45], gamma=0.1, last_epoch=-1)

        orig_stdout = sys.stdout
        with open(readme_path, 'w+') as f:
            sys.stdout = f
            dataset_train.print()
            dataset_test.print()
            print(params_to_update_name)
            print("batch size:", batch_size)
            print(optimizer)
            print(criterion)
            print(scheduler.state_dict())
        sys.stdout = orig_stdout

        since = time.time()
        epoch_since = time.time()
        train_acc_history = []
        val_acc_history = []

        best_model_wts = copy.deepcopy(model.state_dict())
        best_acc = 0.0
        best_epoch = 0
        for epoch in range(num_epochs):
            print('Epoch {}/{}'.format(epoch, num_epochs - 1))
            print('-' * 10)

            scheduler.step()
            #train

            model.train()
            running_loss, correct = 0.0, 0

            for batch, (X, y) in enumerate(loader_train):
                X = X.float().cuda()
                y = y.long().cuda()

                optimizer.zero_grad()

                y_ = model(X)
                loss = criterion(y_, y)

                loss.backward()
                optimizer.step()

                _, y_label_ = torch.max(y_, 1)
                correct += (y_label_ == y).sum().item()
                running_loss += loss.item() * X.shape[0]

            print(f"    train accuracy: {correct/len(loader_train.dataset):0.3f}")
            print(f"    train loss: {running_loss/len(loader_train.dataset):0.3f}")

            train_acc = correct/len(loader_train.dataset)
            train_acc_history.append(train_acc)
            #validation
            model.eval()
            running_loss, correct = 0.0, 0
            with torch.no_grad():
                for batch, (X, y) in enumerate(loader_test):
                    X = X.float().cuda()
                    y = y.long().cuda()

                    y_ = model(X)
                    loss = criterion(y_, y)

                    _, y_label_ = torch.max(y_, 1)
                    correct += (y_label_ == y).sum().item()
                    running_loss += loss.item() * X.shape[0]


            print(f"    validation accuracy: {correct/len(loader_test.dataset):0.3f}")
            print(f"    validation loss: {running_loss/len(loader_test.dataset):0.3f}")

            epoch_acc = correct/len(loader_test.dataset)
            # deep copy the model
            if epoch_acc > best_acc:
                best_acc = epoch_acc
                best_epoch = epoch
                best_model_wts = copy.deepcopy(model.state_dict())

            val_acc_history.append(epoch_acc)
            if epoch % 10 == 0:
                print("save model")
                save_checkpoint(epoch, model, optimizer, scheduler, checkpoint_path+"/{}_epoch.pt".format(epoch))

            time_elapsed = time.time() - since
            print('Epoch complete in {:.0f}m {:.0f}s'.format(time_elapsed // 60, time_elapsed % 60))
            print()

        model.load_state_dict(best_model_wts)
        time_elapsed = time.time() - epoch_since
        epoch_since = time.time()
        print('Training complete in {:.0f}m {:.0f}s'.format(time_elapsed // 60, time_elapsed % 60))
        print('Best val Acc: {:4f}'.format(best_acc))

        torch.save(model.state_dict(), best_model_path)

        orig_stdout = sys.stdout
        with open(stats_path, 'w+') as f:
            sys.stdout = f
            print("numero epoche:", num_epochs)
            print("best model at epoch:", best_epoch)
            print("best accuracy:", best_acc)
            print("train hist")
            print(train_acc_history)
            print("val hist")
            print(val_acc_history)
        sys.stdout = orig_stdout


        train_hist = np.array(train_acc_history)
        val_hist = np.array(val_acc_history)

        fig = plt.figure(figsize=(19.2,10.8), dpi=100)
        plt.title("Validation vs Train")
        plt.xlabel("Training Epochs")
        plt.ylabel("Accuracy")
        plt.plot(range(1,num_epochs+1),train_hist,label="Train")
        plt.plot(range(1,num_epochs+1),val_hist,label="Test")
        plt.ylim((0,1.))
        plt.xticks(np.arange(1, num_epochs+1, 1.0))
        plt.legend()
        fig.savefig(plot_path)

        #matrice confusione
        print("Calc confusion matrix")
        #validation
        model.cuda()
        model.eval()
        #row -> true labels
        #col -> pred labels
        conf_matrix = torch.zeros(num_classes, num_classes)
        with torch.no_grad():
            for batch, (X, y) in enumerate(loader_test):
                X = X.float().cuda()
                y = y.long().cuda()

                y_ = model(X)
                _, y_label_ = torch.max(y_, 1)

                for i in range(len(y)):
                    conf_matrix[y[i].item(), y_label_[i].item()] += 1

        print(conf_matrix)

        bins_labels = dataset_test.bincount()
        bins = [bin for bin,_ in bins_labels]
        print(bins)
        class_to_idx = dataset_test.class_to_idx;

        orig_stdout = sys.stdout
        with open(confusion_matrix_path, 'w+') as f:
            sys.stdout = f
            for i in range(num_classes):
                bin = bins[i].item()
                s = ""
                for j in range(num_classes):
                    conf_matrix[i][j] = conf_matrix[i][j]/bin
                    s+='{:4f},'.format(conf_matrix[i][j].item())
                print(s)
        sys.stdout = orig_stdout

        mean_tot = 0
        for i in range(num_classes):
            mean_tot += conf_matrix[i][i].item()
        mean_tot /= num_classes

        orig_stdout = sys.stdout
        with open(confusion_matrix_path, 'a') as f:
            sys.stdout = f
            print()
            print('accuracy:', mean_tot)
        sys.stdout = orig_stdout