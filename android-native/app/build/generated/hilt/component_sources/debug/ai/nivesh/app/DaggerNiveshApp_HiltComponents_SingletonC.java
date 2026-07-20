package ai.nivesh.app;

import ai.nivesh.app.auth.GoogleSignInClient;
import ai.nivesh.app.auth.TokenStore;
import ai.nivesh.app.data.api.AuthInterceptor;
import ai.nivesh.app.data.api.ChatStreamClient;
import ai.nivesh.app.data.api.NiveshApi;
import ai.nivesh.app.data.repo.AdvisorRepository;
import ai.nivesh.app.data.repo.AuthRepository;
import ai.nivesh.app.data.repo.ChatRepository;
import ai.nivesh.app.data.repo.CompositionRepository;
import ai.nivesh.app.data.repo.DashboardsRepository;
import ai.nivesh.app.data.repo.GoalsRepository;
import ai.nivesh.app.data.repo.HomeRepository;
import ai.nivesh.app.data.repo.InsightsRepository;
import ai.nivesh.app.data.repo.MarketsRepository;
import ai.nivesh.app.data.repo.PlansRepository;
import ai.nivesh.app.data.repo.PortfolioRepository;
import ai.nivesh.app.data.repo.PositionalRepository;
import ai.nivesh.app.data.repo.SettingsRepository;
import ai.nivesh.app.di.NetworkModule_ProvideApiFactory;
import ai.nivesh.app.di.NetworkModule_ProvideJsonFactory;
import ai.nivesh.app.di.NetworkModule_ProvideOkHttpFactory;
import ai.nivesh.app.di.NetworkModule_ProvideRetrofitFactory;
import ai.nivesh.app.ui.RootViewModel;
import ai.nivesh.app.ui.RootViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.advisor.AdvisorViewModel;
import ai.nivesh.app.ui.advisor.AdvisorViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.chat.ChatViewModel;
import ai.nivesh.app.ui.chat.ChatViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.composition.CompositionViewModel;
import ai.nivesh.app.ui.composition.CompositionViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.dashboard.DashboardViewModel;
import ai.nivesh.app.ui.dashboard.DashboardViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.goals.GoalsViewModel;
import ai.nivesh.app.ui.goals.GoalsViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.insights.InsightsViewModel;
import ai.nivesh.app.ui.insights.InsightsViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.login.LoginViewModel;
import ai.nivesh.app.ui.login.LoginViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.markets.MarketsViewModel;
import ai.nivesh.app.ui.markets.MarketsViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.performance.PerformanceViewModel;
import ai.nivesh.app.ui.performance.PerformanceViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.plan.PlanViewModel;
import ai.nivesh.app.ui.plan.PlanViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.portfolio.PortfolioViewModel;
import ai.nivesh.app.ui.portfolio.PortfolioViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.protrader.ProTraderViewModel;
import ai.nivesh.app.ui.protrader.ProTraderViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.recommendations.RecommendationsViewModel;
import ai.nivesh.app.ui.recommendations.RecommendationsViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.risk.RiskViewModel;
import ai.nivesh.app.ui.risk.RiskViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.settings.SettingsViewModel;
import ai.nivesh.app.ui.settings.SettingsViewModel_HiltModules_KeyModule_ProvideFactory;
import ai.nivesh.app.ui.tax.TaxViewModel;
import ai.nivesh.app.ui.tax.TaxViewModel_HiltModules_KeyModule_ProvideFactory;
import android.app.Activity;
import android.app.Service;
import android.view.View;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.SavedStateHandle;
import androidx.lifecycle.ViewModel;
import dagger.hilt.android.ActivityRetainedLifecycle;
import dagger.hilt.android.ViewModelLifecycle;
import dagger.hilt.android.internal.builders.ActivityComponentBuilder;
import dagger.hilt.android.internal.builders.ActivityRetainedComponentBuilder;
import dagger.hilt.android.internal.builders.FragmentComponentBuilder;
import dagger.hilt.android.internal.builders.ServiceComponentBuilder;
import dagger.hilt.android.internal.builders.ViewComponentBuilder;
import dagger.hilt.android.internal.builders.ViewModelComponentBuilder;
import dagger.hilt.android.internal.builders.ViewWithFragmentComponentBuilder;
import dagger.hilt.android.internal.lifecycle.DefaultViewModelFactories;
import dagger.hilt.android.internal.lifecycle.DefaultViewModelFactories_InternalFactoryFactory_Factory;
import dagger.hilt.android.internal.managers.ActivityRetainedComponentManager_LifecycleModule_ProvideActivityRetainedLifecycleFactory;
import dagger.hilt.android.internal.managers.SavedStateHandleHolder;
import dagger.hilt.android.internal.modules.ApplicationContextModule;
import dagger.hilt.android.internal.modules.ApplicationContextModule_ProvideContextFactory;
import dagger.internal.DaggerGenerated;
import dagger.internal.DoubleCheck;
import dagger.internal.MapBuilder;
import dagger.internal.Preconditions;
import dagger.internal.Provider;
import dagger.internal.SetBuilder;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import javax.annotation.processing.Generated;
import kotlinx.serialization.json.Json;
import okhttp3.OkHttpClient;
import retrofit2.Retrofit;

@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class DaggerNiveshApp_HiltComponents_SingletonC {
  private DaggerNiveshApp_HiltComponents_SingletonC() {
  }

  public static Builder builder() {
    return new Builder();
  }

  public static final class Builder {
    private ApplicationContextModule applicationContextModule;

    private Builder() {
    }

    public Builder applicationContextModule(ApplicationContextModule applicationContextModule) {
      this.applicationContextModule = Preconditions.checkNotNull(applicationContextModule);
      return this;
    }

    public NiveshApp_HiltComponents.SingletonC build() {
      Preconditions.checkBuilderRequirement(applicationContextModule, ApplicationContextModule.class);
      return new SingletonCImpl(applicationContextModule);
    }
  }

  private static final class ActivityRetainedCBuilder implements NiveshApp_HiltComponents.ActivityRetainedC.Builder {
    private final SingletonCImpl singletonCImpl;

    private SavedStateHandleHolder savedStateHandleHolder;

    private ActivityRetainedCBuilder(SingletonCImpl singletonCImpl) {
      this.singletonCImpl = singletonCImpl;
    }

    @Override
    public ActivityRetainedCBuilder savedStateHandleHolder(
        SavedStateHandleHolder savedStateHandleHolder) {
      this.savedStateHandleHolder = Preconditions.checkNotNull(savedStateHandleHolder);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.ActivityRetainedC build() {
      Preconditions.checkBuilderRequirement(savedStateHandleHolder, SavedStateHandleHolder.class);
      return new ActivityRetainedCImpl(singletonCImpl, savedStateHandleHolder);
    }
  }

  private static final class ActivityCBuilder implements NiveshApp_HiltComponents.ActivityC.Builder {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private Activity activity;

    private ActivityCBuilder(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
    }

    @Override
    public ActivityCBuilder activity(Activity activity) {
      this.activity = Preconditions.checkNotNull(activity);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.ActivityC build() {
      Preconditions.checkBuilderRequirement(activity, Activity.class);
      return new ActivityCImpl(singletonCImpl, activityRetainedCImpl, activity);
    }
  }

  private static final class FragmentCBuilder implements NiveshApp_HiltComponents.FragmentC.Builder {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl;

    private Fragment fragment;

    private FragmentCBuilder(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl, ActivityCImpl activityCImpl) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
      this.activityCImpl = activityCImpl;
    }

    @Override
    public FragmentCBuilder fragment(Fragment fragment) {
      this.fragment = Preconditions.checkNotNull(fragment);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.FragmentC build() {
      Preconditions.checkBuilderRequirement(fragment, Fragment.class);
      return new FragmentCImpl(singletonCImpl, activityRetainedCImpl, activityCImpl, fragment);
    }
  }

  private static final class ViewWithFragmentCBuilder implements NiveshApp_HiltComponents.ViewWithFragmentC.Builder {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl;

    private final FragmentCImpl fragmentCImpl;

    private View view;

    private ViewWithFragmentCBuilder(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl, ActivityCImpl activityCImpl,
        FragmentCImpl fragmentCImpl) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
      this.activityCImpl = activityCImpl;
      this.fragmentCImpl = fragmentCImpl;
    }

    @Override
    public ViewWithFragmentCBuilder view(View view) {
      this.view = Preconditions.checkNotNull(view);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.ViewWithFragmentC build() {
      Preconditions.checkBuilderRequirement(view, View.class);
      return new ViewWithFragmentCImpl(singletonCImpl, activityRetainedCImpl, activityCImpl, fragmentCImpl, view);
    }
  }

  private static final class ViewCBuilder implements NiveshApp_HiltComponents.ViewC.Builder {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl;

    private View view;

    private ViewCBuilder(SingletonCImpl singletonCImpl, ActivityRetainedCImpl activityRetainedCImpl,
        ActivityCImpl activityCImpl) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
      this.activityCImpl = activityCImpl;
    }

    @Override
    public ViewCBuilder view(View view) {
      this.view = Preconditions.checkNotNull(view);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.ViewC build() {
      Preconditions.checkBuilderRequirement(view, View.class);
      return new ViewCImpl(singletonCImpl, activityRetainedCImpl, activityCImpl, view);
    }
  }

  private static final class ViewModelCBuilder implements NiveshApp_HiltComponents.ViewModelC.Builder {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private SavedStateHandle savedStateHandle;

    private ViewModelLifecycle viewModelLifecycle;

    private ViewModelCBuilder(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
    }

    @Override
    public ViewModelCBuilder savedStateHandle(SavedStateHandle handle) {
      this.savedStateHandle = Preconditions.checkNotNull(handle);
      return this;
    }

    @Override
    public ViewModelCBuilder viewModelLifecycle(ViewModelLifecycle viewModelLifecycle) {
      this.viewModelLifecycle = Preconditions.checkNotNull(viewModelLifecycle);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.ViewModelC build() {
      Preconditions.checkBuilderRequirement(savedStateHandle, SavedStateHandle.class);
      Preconditions.checkBuilderRequirement(viewModelLifecycle, ViewModelLifecycle.class);
      return new ViewModelCImpl(singletonCImpl, activityRetainedCImpl, savedStateHandle, viewModelLifecycle);
    }
  }

  private static final class ServiceCBuilder implements NiveshApp_HiltComponents.ServiceC.Builder {
    private final SingletonCImpl singletonCImpl;

    private Service service;

    private ServiceCBuilder(SingletonCImpl singletonCImpl) {
      this.singletonCImpl = singletonCImpl;
    }

    @Override
    public ServiceCBuilder service(Service service) {
      this.service = Preconditions.checkNotNull(service);
      return this;
    }

    @Override
    public NiveshApp_HiltComponents.ServiceC build() {
      Preconditions.checkBuilderRequirement(service, Service.class);
      return new ServiceCImpl(singletonCImpl, service);
    }
  }

  private static final class ViewWithFragmentCImpl extends NiveshApp_HiltComponents.ViewWithFragmentC {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl;

    private final FragmentCImpl fragmentCImpl;

    private final ViewWithFragmentCImpl viewWithFragmentCImpl = this;

    private ViewWithFragmentCImpl(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl, ActivityCImpl activityCImpl,
        FragmentCImpl fragmentCImpl, View viewParam) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
      this.activityCImpl = activityCImpl;
      this.fragmentCImpl = fragmentCImpl;


    }
  }

  private static final class FragmentCImpl extends NiveshApp_HiltComponents.FragmentC {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl;

    private final FragmentCImpl fragmentCImpl = this;

    private FragmentCImpl(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl, ActivityCImpl activityCImpl,
        Fragment fragmentParam) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
      this.activityCImpl = activityCImpl;


    }

    @Override
    public DefaultViewModelFactories.InternalFactoryFactory getHiltInternalFactoryFactory() {
      return activityCImpl.getHiltInternalFactoryFactory();
    }

    @Override
    public ViewWithFragmentComponentBuilder viewWithFragmentComponentBuilder() {
      return new ViewWithFragmentCBuilder(singletonCImpl, activityRetainedCImpl, activityCImpl, fragmentCImpl);
    }
  }

  private static final class ViewCImpl extends NiveshApp_HiltComponents.ViewC {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl;

    private final ViewCImpl viewCImpl = this;

    private ViewCImpl(SingletonCImpl singletonCImpl, ActivityRetainedCImpl activityRetainedCImpl,
        ActivityCImpl activityCImpl, View viewParam) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;
      this.activityCImpl = activityCImpl;


    }
  }

  private static final class ActivityCImpl extends NiveshApp_HiltComponents.ActivityC {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ActivityCImpl activityCImpl = this;

    private ActivityCImpl(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl, Activity activityParam) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;


    }

    @Override
    public void injectMainActivity(MainActivity arg0) {
    }

    @Override
    public DefaultViewModelFactories.InternalFactoryFactory getHiltInternalFactoryFactory() {
      return DefaultViewModelFactories_InternalFactoryFactory_Factory.newInstance(getViewModelKeys(), new ViewModelCBuilder(singletonCImpl, activityRetainedCImpl));
    }

    @Override
    public Set<String> getViewModelKeys() {
      return SetBuilder.<String>newSetBuilder(17).add(AdvisorViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(ChatViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(CompositionViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(DashboardViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(GoalsViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(InsightsViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(LoginViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(MarketsViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(PerformanceViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(PlanViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(PortfolioViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(ProTraderViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(RecommendationsViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(RiskViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(RootViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(SettingsViewModel_HiltModules_KeyModule_ProvideFactory.provide()).add(TaxViewModel_HiltModules_KeyModule_ProvideFactory.provide()).build();
    }

    @Override
    public ViewModelComponentBuilder getViewModelComponentBuilder() {
      return new ViewModelCBuilder(singletonCImpl, activityRetainedCImpl);
    }

    @Override
    public FragmentComponentBuilder fragmentComponentBuilder() {
      return new FragmentCBuilder(singletonCImpl, activityRetainedCImpl, activityCImpl);
    }

    @Override
    public ViewComponentBuilder viewComponentBuilder() {
      return new ViewCBuilder(singletonCImpl, activityRetainedCImpl, activityCImpl);
    }
  }

  private static final class ViewModelCImpl extends NiveshApp_HiltComponents.ViewModelC {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl;

    private final ViewModelCImpl viewModelCImpl = this;

    private Provider<AdvisorViewModel> advisorViewModelProvider;

    private Provider<ChatViewModel> chatViewModelProvider;

    private Provider<CompositionViewModel> compositionViewModelProvider;

    private Provider<DashboardViewModel> dashboardViewModelProvider;

    private Provider<GoalsViewModel> goalsViewModelProvider;

    private Provider<InsightsViewModel> insightsViewModelProvider;

    private Provider<LoginViewModel> loginViewModelProvider;

    private Provider<MarketsViewModel> marketsViewModelProvider;

    private Provider<PerformanceViewModel> performanceViewModelProvider;

    private Provider<PlanViewModel> planViewModelProvider;

    private Provider<PortfolioViewModel> portfolioViewModelProvider;

    private Provider<ProTraderViewModel> proTraderViewModelProvider;

    private Provider<RecommendationsViewModel> recommendationsViewModelProvider;

    private Provider<RiskViewModel> riskViewModelProvider;

    private Provider<RootViewModel> rootViewModelProvider;

    private Provider<SettingsViewModel> settingsViewModelProvider;

    private Provider<TaxViewModel> taxViewModelProvider;

    private ViewModelCImpl(SingletonCImpl singletonCImpl,
        ActivityRetainedCImpl activityRetainedCImpl, SavedStateHandle savedStateHandleParam,
        ViewModelLifecycle viewModelLifecycleParam) {
      this.singletonCImpl = singletonCImpl;
      this.activityRetainedCImpl = activityRetainedCImpl;

      initialize(savedStateHandleParam, viewModelLifecycleParam);

    }

    @SuppressWarnings("unchecked")
    private void initialize(final SavedStateHandle savedStateHandleParam,
        final ViewModelLifecycle viewModelLifecycleParam) {
      this.advisorViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 0);
      this.chatViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 1);
      this.compositionViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 2);
      this.dashboardViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 3);
      this.goalsViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 4);
      this.insightsViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 5);
      this.loginViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 6);
      this.marketsViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 7);
      this.performanceViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 8);
      this.planViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 9);
      this.portfolioViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 10);
      this.proTraderViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 11);
      this.recommendationsViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 12);
      this.riskViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 13);
      this.rootViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 14);
      this.settingsViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 15);
      this.taxViewModelProvider = new SwitchingProvider<>(singletonCImpl, activityRetainedCImpl, viewModelCImpl, 16);
    }

    @Override
    public Map<String, javax.inject.Provider<ViewModel>> getHiltViewModelMap() {
      return MapBuilder.<String, javax.inject.Provider<ViewModel>>newMapBuilder(17).put("ai.nivesh.app.ui.advisor.AdvisorViewModel", ((Provider) advisorViewModelProvider)).put("ai.nivesh.app.ui.chat.ChatViewModel", ((Provider) chatViewModelProvider)).put("ai.nivesh.app.ui.composition.CompositionViewModel", ((Provider) compositionViewModelProvider)).put("ai.nivesh.app.ui.dashboard.DashboardViewModel", ((Provider) dashboardViewModelProvider)).put("ai.nivesh.app.ui.goals.GoalsViewModel", ((Provider) goalsViewModelProvider)).put("ai.nivesh.app.ui.insights.InsightsViewModel", ((Provider) insightsViewModelProvider)).put("ai.nivesh.app.ui.login.LoginViewModel", ((Provider) loginViewModelProvider)).put("ai.nivesh.app.ui.markets.MarketsViewModel", ((Provider) marketsViewModelProvider)).put("ai.nivesh.app.ui.performance.PerformanceViewModel", ((Provider) performanceViewModelProvider)).put("ai.nivesh.app.ui.plan.PlanViewModel", ((Provider) planViewModelProvider)).put("ai.nivesh.app.ui.portfolio.PortfolioViewModel", ((Provider) portfolioViewModelProvider)).put("ai.nivesh.app.ui.protrader.ProTraderViewModel", ((Provider) proTraderViewModelProvider)).put("ai.nivesh.app.ui.recommendations.RecommendationsViewModel", ((Provider) recommendationsViewModelProvider)).put("ai.nivesh.app.ui.risk.RiskViewModel", ((Provider) riskViewModelProvider)).put("ai.nivesh.app.ui.RootViewModel", ((Provider) rootViewModelProvider)).put("ai.nivesh.app.ui.settings.SettingsViewModel", ((Provider) settingsViewModelProvider)).put("ai.nivesh.app.ui.tax.TaxViewModel", ((Provider) taxViewModelProvider)).build();
    }

    @Override
    public Map<String, Object> getHiltViewModelAssistedMap() {
      return Collections.<String, Object>emptyMap();
    }

    private static final class SwitchingProvider<T> implements Provider<T> {
      private final SingletonCImpl singletonCImpl;

      private final ActivityRetainedCImpl activityRetainedCImpl;

      private final ViewModelCImpl viewModelCImpl;

      private final int id;

      SwitchingProvider(SingletonCImpl singletonCImpl, ActivityRetainedCImpl activityRetainedCImpl,
          ViewModelCImpl viewModelCImpl, int id) {
        this.singletonCImpl = singletonCImpl;
        this.activityRetainedCImpl = activityRetainedCImpl;
        this.viewModelCImpl = viewModelCImpl;
        this.id = id;
      }

      @SuppressWarnings("unchecked")
      @Override
      public T get() {
        switch (id) {
          case 0: // ai.nivesh.app.ui.advisor.AdvisorViewModel 
          return (T) new AdvisorViewModel(singletonCImpl.advisorRepositoryProvider.get());

          case 1: // ai.nivesh.app.ui.chat.ChatViewModel 
          return (T) new ChatViewModel(singletonCImpl.chatRepositoryProvider.get());

          case 2: // ai.nivesh.app.ui.composition.CompositionViewModel 
          return (T) new CompositionViewModel(singletonCImpl.compositionRepositoryProvider.get());

          case 3: // ai.nivesh.app.ui.dashboard.DashboardViewModel 
          return (T) new DashboardViewModel(singletonCImpl.homeRepositoryProvider.get());

          case 4: // ai.nivesh.app.ui.goals.GoalsViewModel 
          return (T) new GoalsViewModel(singletonCImpl.goalsRepositoryProvider.get());

          case 5: // ai.nivesh.app.ui.insights.InsightsViewModel 
          return (T) new InsightsViewModel(singletonCImpl.insightsRepositoryProvider.get());

          case 6: // ai.nivesh.app.ui.login.LoginViewModel 
          return (T) new LoginViewModel(singletonCImpl.authRepositoryProvider.get());

          case 7: // ai.nivesh.app.ui.markets.MarketsViewModel 
          return (T) new MarketsViewModel(singletonCImpl.marketsRepositoryProvider.get());

          case 8: // ai.nivesh.app.ui.performance.PerformanceViewModel 
          return (T) new PerformanceViewModel(singletonCImpl.dashboardsRepositoryProvider.get());

          case 9: // ai.nivesh.app.ui.plan.PlanViewModel 
          return (T) new PlanViewModel(singletonCImpl.plansRepositoryProvider.get());

          case 10: // ai.nivesh.app.ui.portfolio.PortfolioViewModel 
          return (T) new PortfolioViewModel(singletonCImpl.portfolioRepositoryProvider.get());

          case 11: // ai.nivesh.app.ui.protrader.ProTraderViewModel 
          return (T) new ProTraderViewModel(singletonCImpl.positionalRepositoryProvider.get());

          case 12: // ai.nivesh.app.ui.recommendations.RecommendationsViewModel 
          return (T) new RecommendationsViewModel(singletonCImpl.plansRepositoryProvider.get());

          case 13: // ai.nivesh.app.ui.risk.RiskViewModel 
          return (T) new RiskViewModel(singletonCImpl.dashboardsRepositoryProvider.get());

          case 14: // ai.nivesh.app.ui.RootViewModel 
          return (T) new RootViewModel(singletonCImpl.authRepositoryProvider.get());

          case 15: // ai.nivesh.app.ui.settings.SettingsViewModel 
          return (T) new SettingsViewModel(singletonCImpl.settingsRepositoryProvider.get(), singletonCImpl.authRepositoryProvider.get());

          case 16: // ai.nivesh.app.ui.tax.TaxViewModel 
          return (T) new TaxViewModel(singletonCImpl.dashboardsRepositoryProvider.get());

          default: throw new AssertionError(id);
        }
      }
    }
  }

  private static final class ActivityRetainedCImpl extends NiveshApp_HiltComponents.ActivityRetainedC {
    private final SingletonCImpl singletonCImpl;

    private final ActivityRetainedCImpl activityRetainedCImpl = this;

    private Provider<ActivityRetainedLifecycle> provideActivityRetainedLifecycleProvider;

    private ActivityRetainedCImpl(SingletonCImpl singletonCImpl,
        SavedStateHandleHolder savedStateHandleHolderParam) {
      this.singletonCImpl = singletonCImpl;

      initialize(savedStateHandleHolderParam);

    }

    @SuppressWarnings("unchecked")
    private void initialize(final SavedStateHandleHolder savedStateHandleHolderParam) {
      this.provideActivityRetainedLifecycleProvider = DoubleCheck.provider(new SwitchingProvider<ActivityRetainedLifecycle>(singletonCImpl, activityRetainedCImpl, 0));
    }

    @Override
    public ActivityComponentBuilder activityComponentBuilder() {
      return new ActivityCBuilder(singletonCImpl, activityRetainedCImpl);
    }

    @Override
    public ActivityRetainedLifecycle getActivityRetainedLifecycle() {
      return provideActivityRetainedLifecycleProvider.get();
    }

    private static final class SwitchingProvider<T> implements Provider<T> {
      private final SingletonCImpl singletonCImpl;

      private final ActivityRetainedCImpl activityRetainedCImpl;

      private final int id;

      SwitchingProvider(SingletonCImpl singletonCImpl, ActivityRetainedCImpl activityRetainedCImpl,
          int id) {
        this.singletonCImpl = singletonCImpl;
        this.activityRetainedCImpl = activityRetainedCImpl;
        this.id = id;
      }

      @SuppressWarnings("unchecked")
      @Override
      public T get() {
        switch (id) {
          case 0: // dagger.hilt.android.ActivityRetainedLifecycle 
          return (T) ActivityRetainedComponentManager_LifecycleModule_ProvideActivityRetainedLifecycleFactory.provideActivityRetainedLifecycle();

          default: throw new AssertionError(id);
        }
      }
    }
  }

  private static final class ServiceCImpl extends NiveshApp_HiltComponents.ServiceC {
    private final SingletonCImpl singletonCImpl;

    private final ServiceCImpl serviceCImpl = this;

    private ServiceCImpl(SingletonCImpl singletonCImpl, Service serviceParam) {
      this.singletonCImpl = singletonCImpl;


    }
  }

  private static final class SingletonCImpl extends NiveshApp_HiltComponents.SingletonC {
    private final ApplicationContextModule applicationContextModule;

    private final SingletonCImpl singletonCImpl = this;

    private Provider<TokenStore> tokenStoreProvider;

    private Provider<OkHttpClient> provideOkHttpProvider;

    private Provider<Json> provideJsonProvider;

    private Provider<Retrofit> provideRetrofitProvider;

    private Provider<NiveshApi> provideApiProvider;

    private Provider<AdvisorRepository> advisorRepositoryProvider;

    private Provider<ChatStreamClient> chatStreamClientProvider;

    private Provider<ChatRepository> chatRepositoryProvider;

    private Provider<CompositionRepository> compositionRepositoryProvider;

    private Provider<PortfolioRepository> portfolioRepositoryProvider;

    private Provider<HomeRepository> homeRepositoryProvider;

    private Provider<GoalsRepository> goalsRepositoryProvider;

    private Provider<InsightsRepository> insightsRepositoryProvider;

    private Provider<GoogleSignInClient> googleSignInClientProvider;

    private Provider<AuthRepository> authRepositoryProvider;

    private Provider<MarketsRepository> marketsRepositoryProvider;

    private Provider<DashboardsRepository> dashboardsRepositoryProvider;

    private Provider<PlansRepository> plansRepositoryProvider;

    private Provider<PositionalRepository> positionalRepositoryProvider;

    private Provider<SettingsRepository> settingsRepositoryProvider;

    private SingletonCImpl(ApplicationContextModule applicationContextModuleParam) {
      this.applicationContextModule = applicationContextModuleParam;
      initialize(applicationContextModuleParam);

    }

    private AuthInterceptor authInterceptor() {
      return new AuthInterceptor(tokenStoreProvider.get());
    }

    @SuppressWarnings("unchecked")
    private void initialize(final ApplicationContextModule applicationContextModuleParam) {
      this.tokenStoreProvider = DoubleCheck.provider(new SwitchingProvider<TokenStore>(singletonCImpl, 4));
      this.provideOkHttpProvider = DoubleCheck.provider(new SwitchingProvider<OkHttpClient>(singletonCImpl, 3));
      this.provideJsonProvider = DoubleCheck.provider(new SwitchingProvider<Json>(singletonCImpl, 5));
      this.provideRetrofitProvider = DoubleCheck.provider(new SwitchingProvider<Retrofit>(singletonCImpl, 2));
      this.provideApiProvider = DoubleCheck.provider(new SwitchingProvider<NiveshApi>(singletonCImpl, 1));
      this.advisorRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<AdvisorRepository>(singletonCImpl, 0));
      this.chatStreamClientProvider = DoubleCheck.provider(new SwitchingProvider<ChatStreamClient>(singletonCImpl, 7));
      this.chatRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<ChatRepository>(singletonCImpl, 6));
      this.compositionRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<CompositionRepository>(singletonCImpl, 8));
      this.portfolioRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<PortfolioRepository>(singletonCImpl, 10));
      this.homeRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<HomeRepository>(singletonCImpl, 9));
      this.goalsRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<GoalsRepository>(singletonCImpl, 11));
      this.insightsRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<InsightsRepository>(singletonCImpl, 12));
      this.googleSignInClientProvider = DoubleCheck.provider(new SwitchingProvider<GoogleSignInClient>(singletonCImpl, 14));
      this.authRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<AuthRepository>(singletonCImpl, 13));
      this.marketsRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<MarketsRepository>(singletonCImpl, 15));
      this.dashboardsRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<DashboardsRepository>(singletonCImpl, 16));
      this.plansRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<PlansRepository>(singletonCImpl, 17));
      this.positionalRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<PositionalRepository>(singletonCImpl, 18));
      this.settingsRepositoryProvider = DoubleCheck.provider(new SwitchingProvider<SettingsRepository>(singletonCImpl, 19));
    }

    @Override
    public void injectNiveshApp(NiveshApp niveshApp) {
    }

    @Override
    public Set<Boolean> getDisableFragmentGetContextFix() {
      return Collections.<Boolean>emptySet();
    }

    @Override
    public ActivityRetainedComponentBuilder retainedComponentBuilder() {
      return new ActivityRetainedCBuilder(singletonCImpl);
    }

    @Override
    public ServiceComponentBuilder serviceComponentBuilder() {
      return new ServiceCBuilder(singletonCImpl);
    }

    private static final class SwitchingProvider<T> implements Provider<T> {
      private final SingletonCImpl singletonCImpl;

      private final int id;

      SwitchingProvider(SingletonCImpl singletonCImpl, int id) {
        this.singletonCImpl = singletonCImpl;
        this.id = id;
      }

      @SuppressWarnings("unchecked")
      @Override
      public T get() {
        switch (id) {
          case 0: // ai.nivesh.app.data.repo.AdvisorRepository 
          return (T) new AdvisorRepository(singletonCImpl.provideApiProvider.get());

          case 1: // ai.nivesh.app.data.api.NiveshApi 
          return (T) NetworkModule_ProvideApiFactory.provideApi(singletonCImpl.provideRetrofitProvider.get());

          case 2: // retrofit2.Retrofit 
          return (T) NetworkModule_ProvideRetrofitFactory.provideRetrofit(singletonCImpl.provideOkHttpProvider.get(), singletonCImpl.provideJsonProvider.get());

          case 3: // okhttp3.OkHttpClient 
          return (T) NetworkModule_ProvideOkHttpFactory.provideOkHttp(singletonCImpl.authInterceptor());

          case 4: // ai.nivesh.app.auth.TokenStore 
          return (T) new TokenStore(ApplicationContextModule_ProvideContextFactory.provideContext(singletonCImpl.applicationContextModule));

          case 5: // kotlinx.serialization.json.Json 
          return (T) NetworkModule_ProvideJsonFactory.provideJson();

          case 6: // ai.nivesh.app.data.repo.ChatRepository 
          return (T) new ChatRepository(singletonCImpl.provideApiProvider.get(), singletonCImpl.chatStreamClientProvider.get());

          case 7: // ai.nivesh.app.data.api.ChatStreamClient 
          return (T) new ChatStreamClient(singletonCImpl.provideOkHttpProvider.get(), singletonCImpl.provideJsonProvider.get());

          case 8: // ai.nivesh.app.data.repo.CompositionRepository 
          return (T) new CompositionRepository(singletonCImpl.provideApiProvider.get());

          case 9: // ai.nivesh.app.data.repo.HomeRepository 
          return (T) new HomeRepository(singletonCImpl.provideApiProvider.get(), singletonCImpl.portfolioRepositoryProvider.get());

          case 10: // ai.nivesh.app.data.repo.PortfolioRepository 
          return (T) new PortfolioRepository(singletonCImpl.provideApiProvider.get());

          case 11: // ai.nivesh.app.data.repo.GoalsRepository 
          return (T) new GoalsRepository(singletonCImpl.provideApiProvider.get());

          case 12: // ai.nivesh.app.data.repo.InsightsRepository 
          return (T) new InsightsRepository(singletonCImpl.provideApiProvider.get());

          case 13: // ai.nivesh.app.data.repo.AuthRepository 
          return (T) new AuthRepository(singletonCImpl.provideApiProvider.get(), singletonCImpl.tokenStoreProvider.get(), singletonCImpl.googleSignInClientProvider.get());

          case 14: // ai.nivesh.app.auth.GoogleSignInClient 
          return (T) new GoogleSignInClient(ApplicationContextModule_ProvideContextFactory.provideContext(singletonCImpl.applicationContextModule));

          case 15: // ai.nivesh.app.data.repo.MarketsRepository 
          return (T) new MarketsRepository(singletonCImpl.provideApiProvider.get());

          case 16: // ai.nivesh.app.data.repo.DashboardsRepository 
          return (T) new DashboardsRepository(singletonCImpl.provideApiProvider.get());

          case 17: // ai.nivesh.app.data.repo.PlansRepository 
          return (T) new PlansRepository(singletonCImpl.provideApiProvider.get());

          case 18: // ai.nivesh.app.data.repo.PositionalRepository 
          return (T) new PositionalRepository(singletonCImpl.provideApiProvider.get());

          case 19: // ai.nivesh.app.data.repo.SettingsRepository 
          return (T) new SettingsRepository(singletonCImpl.provideApiProvider.get());

          default: throw new AssertionError(id);
        }
      }
    }
  }
}
